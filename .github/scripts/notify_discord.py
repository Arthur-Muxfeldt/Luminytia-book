#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Posta em um webhook do Discord o que mudou no livro de Luminytia.

Compara os <element> de todos os XMLs entre dois commits e monta um resumo
com o que foi adicionado, alterado e removido.

Variáveis de ambiente:
  DISCORD_WEBHOOK_URL  webhook do canal (obrigatório, exceto com DRY_RUN=1)
  BEFORE_SHA           commit anterior (github.event.before)
  AFTER_SHA            commit novo (github.sha); padrão HEAD
  REPO, ACTOR, COMMIT_URL, COMMIT_MESSAGE   contexto opcional para o rodapé
  DRY_RUN=1            imprime o payload em vez de enviar
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# Tipos que ganham linha própria no post; o resto vira contagem resumida.
MAIN_TYPES = ("Source", "Class", "Archetype", "Race", "Background", "Feat",
              "Spell", "Magic Item", "Item", "Monster", "Companion")

PT = {
    "Source": ("fonte", "fontes"),
    "Class": ("classe", "classes"),
    "Archetype": ("arquétipo", "arquétipos"),
    "Race": ("raça", "raças"),
    "Background": ("antecedente", "antecedentes"),
    "Feat": ("talento", "talentos"),
    "Spell": ("magia", "magias"),
    "Magic Item": ("item mágico", "itens mágicos"),
    "Item": ("item", "itens"),
    "Monster": ("criatura", "criaturas"),
    "Companion": ("companheiro", "companheiros"),
    "Class Feature": ("habilidade de classe", "habilidades de classe"),
    "Archetype Feature": ("habilidade de arquétipo", "habilidades de arquétipo"),
    "Racial Trait": ("traço racial", "traços raciais"),
    "Proficiency": ("proficiência", "proficiências"),
    "Grants": ("concessão", "concessões"),
    "Rule": ("regra", "regras"),
    "Deity": ("divindade", "divindades"),
}

SCHOOLS = {
    "Abjuration": "abjuração", "Conjuration": "conjuração", "Divination": "adivinhação",
    "Enchantment": "encantamento", "Evocation": "evocação", "Illusion": "ilusão",
    "Necromancy": "necromancia", "Transmutation": "transmutação",
}

COLOR = 0xE8B14A          # dourado de Luminytia
MAX_EMBED_DESC = 3800     # limite do Discord é 4096; folga para o rodapé
NAMES_PER_SECTION = 40


# ---------------------------------------------------------------- git

def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(("git",) + args, capture_output=True, text=True)


def rev(ref: str | None) -> str | None:
    """Resolve um ref para um commit, ou None se não existir/for o zero sha."""
    if not ref or set(ref.strip()) == {"0"}:
        return None
    out = git("rev-parse", "--verify", "--quiet", ref.strip() + "^{commit}").stdout.strip()
    return out or None


def show(ref: str, path: str) -> str | None:
    p = git("show", f"{ref}:{path}")
    return p.stdout if p.returncode == 0 else None


def xml_files(ref: str) -> list[str]:
    out = git("ls-tree", "-r", "--name-only", ref).stdout
    return [line for line in out.splitlines() if line.endswith(".xml")]


# ---------------------------------------------------------------- parsing

def parse_elements(text: str | None, path: str) -> dict[str, dict]:
    els: dict[str, dict] = {}
    if not text:
        return els
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        print(f"::warning file={path}::XML inválido ({exc}); arquivo ignorado", file=sys.stderr)
        return els
    for i, el in enumerate(root.iter("element")):
        name = (el.get("name") or "sem nome").strip()
        typ = (el.get("type") or "?").strip()
        key = el.get("id") or f"{path}#{typ}#{name}#{i}"
        setters = {s.get("name"): (s.text or "").strip() for s in el.findall("./setters/set")}
        raw = ET.tostring(el, encoding="unicode")
        try:
            body = ET.canonicalize(raw, strip_text=True)
        except Exception:
            body = raw
        els[key] = {"name": name, "type": typ, "path": path, "setters": setters, "body": body}
    return els


def snapshot(ref: str | None) -> dict[str, dict]:
    """Todos os elementos do livro em um commit, indexados por id."""
    out: dict[str, dict] = {}
    if ref is None:
        return out
    for path in xml_files(ref):
        out.update(parse_elements(show(ref, path), path))
    return out


def index_version(ref: str | None) -> str | None:
    if ref is None:
        return None
    text = show(ref, "Luminytia.index")
    if not text:
        return None
    try:
        node = ET.fromstring(text).find("./info/update")
    except ET.ParseError:
        return None
    return node.get("version") if node is not None else None


# ---------------------------------------------------------------- texto

def plural(typ: str, n: int) -> str:
    sing, plur = PT.get(typ, (typ.lower(), typ.lower()))
    return plur if n != 1 else sing


def label(el: dict, old_name: str | None = None) -> str:
    name = f"**{el['name']}**"
    if old_name and old_name != el["name"]:
        name = f"**{old_name} → {el['name']}**"
    if el["type"] == "Spell":
        bits = []
        lvl = el["setters"].get("level")
        if lvl == "0":
            bits.append("truque")
        elif lvl:
            bits.append(f"nível {lvl}")
        school = el["setters"].get("school", "")
        if school:
            bits.append(SCHOOLS.get(school, school.lower()))
        if bits:
            return f"{name} ({', '.join(bits)})"
    return name


def render_section(header: str, entries: list[tuple[dict, str | None]]) -> list[str]:
    """Uma seção (adicionados/alterados/removidos) como linhas de markdown."""
    if not entries:
        return []
    lines = [header]
    groups: dict[str, list[tuple[dict, str | None]]] = {}
    for el, old in entries:
        groups.setdefault(el["type"], []).append((el, old))

    shown = 0
    minor: list[tuple[str, int]] = []
    order = sorted(groups, key=lambda t: (MAIN_TYPES.index(t) if t in MAIN_TYPES else 99, t))
    for typ in order:
        group = sorted(groups[typ], key=lambda pair: pair[0]["name"].lower())
        if typ not in MAIN_TYPES:
            minor.append((typ, len(group)))
            continue
        lines.append(f"__{plural(typ, len(group)).capitalize()}__")
        take = group[:max(NAMES_PER_SECTION - shown, 0)]
        for el, old in take:
            lines.append(f"• {label(el, old)}")
        shown += len(take)
        rest = len(group) - len(take)
        if rest:
            lines.append(f"• …e mais {rest} {plural(typ, rest)}")
    if minor:
        parts = [f"{count} {plural(typ, count)}" for typ, count in sorted(minor)]
        lines.append(f"_+ {', '.join(parts)}_")
    lines.append("")
    return lines


def chunk(lines: list[str]) -> list[str]:
    """Quebra o corpo em pedaços que cabem em um embed."""
    chunks, current = [], ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > MAX_EMBED_DESC and current:
            chunks.append(current)
            current = line
        else:
            current = candidate[:MAX_EMBED_DESC]
    if current.strip():
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- envio

def post(webhook: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "luminytia-book/1.0"}
    for attempt in range(5):
        req = urllib.request.Request(webhook, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20):
                return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 429:
                wait = 5.0
                try:
                    wait = float(json.loads(body).get("retry_after", 5))
                except Exception:
                    pass
                time.sleep(min(wait, 30))
                continue
            if 500 <= exc.code < 600:
                time.sleep(2 * (attempt + 1))
                continue
            raise SystemExit(f"::error::Discord respondeu {exc.code}: {body}")
        except urllib.error.URLError:
            time.sleep(2 * (attempt + 1))
    raise SystemExit("::error::não consegui falar com o Discord depois de 5 tentativas")


# ---------------------------------------------------------------- main

def main() -> int:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    dry_run = os.environ.get("DRY_RUN") == "1"
    if not webhook and not dry_run:
        print("::error::DISCORD_WEBHOOK_URL não está configurado (Settings → Secrets)")
        return 1

    after = rev(os.environ.get("AFTER_SHA") or "HEAD")
    if after is None:
        print("::error::não consegui resolver o commit atual")
        return 1
    before = rev(os.environ.get("BEFORE_SHA")) or rev(f"{after}^")

    old = snapshot(before)
    new = snapshot(after)

    added = [(new[k], None) for k in new.keys() - old.keys()]
    removed = [(old[k], None) for k in old.keys() - new.keys()]
    changed = [
        (new[k], old[k]["name"])
        for k in new.keys() & old.keys()
        if new[k]["body"] != old[k]["body"]
    ]

    if not (added or removed or changed):
        print("Nada de novo no livro; nenhuma mensagem enviada.")
        return 0

    lines: list[str] = []
    lines += render_section(f"**Adicionado** ({len(added)})", added)
    lines += render_section(f"**Alterado** ({len(changed)})", changed)
    lines += render_section(f"**Removido** ({len(removed)})", removed)

    v_old, v_new = index_version(before), index_version(after)
    title = "Luminytia — o livro foi atualizado"
    if v_new and v_new != v_old:
        title = f"Luminytia {v_new} — o livro foi atualizado"
    if before is None:
        title = "Luminytia — o livro foi publicado"

    message = (os.environ.get("COMMIT_MESSAGE") or "").strip().splitlines()
    footer = message[0][:120] if message else f"commit {after[:7]}"
    actor = os.environ.get("ACTOR")
    if actor:
        footer = f"{footer} — por {actor}"

    bodies = chunk(lines)
    embeds = []
    for i, body in enumerate(bodies):
        embed: dict = {"description": body, "color": COLOR}
        if i == 0:
            embed["title"] = title
            if os.environ.get("COMMIT_URL"):
                embed["url"] = os.environ["COMMIT_URL"]
        if i == len(bodies) - 1:
            embed["footer"] = {"text": footer}
        embeds.append(embed)

    for i in range(0, len(embeds), 10):
        payload = {"username": "Luminytia", "embeds": embeds[i:i + 10]}
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            post(webhook, payload)
    if not dry_run:
        print(f"Enviado ao Discord: +{len(added)} ~{len(changed)} -{len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
