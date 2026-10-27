# stt/voice_commands.py
"""
Voice command detection.
Runs over transcribed text before it is typed.
Returns either the original text, a modified version, or a special action.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass


@dataclass
class CommandResult:
    text: str             # Text to type (may be empty)
    delete_last: bool = False  # Trigger delete-last-segment action
    action: str = ""      # Special action name if any


DELETE = "__DELETE__"

# Command tables, one per language selectable in Settings.
# Format: {phrase: replacement_or_action}. Phrases are matched after
# _normalize(), so case, hyphens and trailing punctuation do not matter.
_COMMANDS: dict[str, dict[str, str]] = {
    "en": {
        "new line": "\n", "next line": "\n",
        "new paragraph": "\n\n",
        "period": ".", "full stop": ".",
        "comma": ",",
        "question mark": "?",
        "exclamation mark": "!", "exclamation point": "!",
        "colon": ":",
        "semicolon": ";",
        "open bracket": "(", "open parenthesis": "(",
        "close bracket": ")", "close parenthesis": ")",
        "delete that": DELETE, "undo that": DELETE, "scratch that": DELETE,
    },
    "de": {
        "neue zeile": "\n",
        "neuer absatz": "\n\n",
        "punkt": ".",
        "komma": ",",
        "fragezeichen": "?",
        "ausrufezeichen": "!",
        "doppelpunkt": ":",
        "semikolon": ";", "strichpunkt": ";",
        "klammer auf": "(",
        "klammer zu": ")",
        "löschen": DELETE, "rückgängig": DELETE,
    },
    "fr": {
        "nouvelle ligne": "\n", "à la ligne": "\n", "retour à la ligne": "\n",
        "nouveau paragraphe": "\n\n",
        "point": ".",
        "virgule": ",",
        "point d'interrogation": "?",
        "point d'exclamation": "!",
        "deux points": ":",
        "point virgule": ";",
        "ouvrez la parenthèse": "(", "ouvrir la parenthèse": "(",
        "fermez la parenthèse": ")", "fermer la parenthèse": ")",
        "supprimer": DELETE, "effacer": DELETE, "annuler": DELETE,
    },
    "es": {
        "nueva línea": "\n", "nueva linea": "\n",
        "nuevo párrafo": "\n\n", "nuevo parrafo": "\n\n",
        "punto": ".",
        "coma": ",",
        "signo de interrogación": "?", "signo de pregunta": "?",
        "signo de exclamación": "!",
        "dos puntos": ":",
        "punto y coma": ";",
        "abrir paréntesis": "(", "abre paréntesis": "(",
        "cerrar paréntesis": ")", "cierra paréntesis": ")",
        "borrar eso": DELETE, "borrar": DELETE, "deshacer": DELETE,
    },
    "it": {
        "a capo": "\n", "acapo": "\n", "nuova riga": "\n",
        "nuovo paragrafo": "\n\n",
        "punto": ".",
        "virgola": ",",
        "punto interrogativo": "?", "punto di domanda": "?",
        "punto esclamativo": "!",
        "due punti": ":",
        "punto e virgola": ";",
        "apri parentesi": "(", "aperta parentesi": "(",
        "chiudi parentesi": ")", "chiusa parentesi": ")",
        "cancella": DELETE, "annulla": DELETE,
    },
    "pt": {
        "nova linha": "\n",
        "novo parágrafo": "\n\n",
        "ponto": ".", "ponto final": ".",
        "vírgula": ",",
        "ponto de interrogação": "?",
        "ponto de exclamação": "!",
        "dois pontos": ":",
        "ponto e vírgula": ";",
        "abrir parênteses": "(", "abre parênteses": "(",
        "fechar parênteses": ")", "fecha parênteses": ")",
        "apagar isso": DELETE, "apagar": DELETE, "desfazer": DELETE,
    },
    "ja": {
        "改行": "\n", "新しい行": "\n",
        "新しい段落": "\n\n",
        "句点": "。", "まる": "。",
        "読点": "、", "てん": "、",
        "疑問符": "？", "はてな": "？",
        "感嘆符": "！", "びっくりマーク": "！",
        "コロン": "：",
        "セミコロン": "；",
        "かっこ": "（", "かっこ開き": "（",
        "かっこ閉じ": "）",
        "削除": DELETE, "取り消し": DELETE,
    },
    "zh": {
        "换行": "\n", "換行": "\n",
        "新段落": "\n\n",
        "句号": "。", "句號": "。",
        "逗号": "，", "逗號": "，",
        "顿号": "、", "頓號": "、",
        "问号": "？", "問號": "？",
        "感叹号": "！", "感嘆號": "！",
        "冒号": "：", "冒號": "：",
        "分号": "；", "分號": "；",
        "左括号": "（", "左括號": "（",
        "右括号": "）", "右括號": "）",
        "删除": DELETE, "刪除": DELETE, "撤销": DELETE, "撤銷": DELETE,
    },
    "ko": {
        "줄 바꿈": "\n", "줄바꿈": "\n", "새 줄": "\n",
        "새 단락": "\n\n", "새 문단": "\n\n",
        "마침표": ".",
        "쉼표": ",",
        "물음표": "?",
        "느낌표": "!",
        "콜론": ":",
        "세미콜론": ";",
        "괄호 열기": "(",
        "괄호 닫기": ")",
        "삭제": DELETE, "지워": DELETE,
    },
    "nl": {
        "nieuwe regel": "\n",
        "nieuwe alinea": "\n\n",
        "punt": ".",
        "komma": ",",
        "vraagteken": "?",
        "uitroepteken": "!",
        "dubbele punt": ":",
        "puntkomma": ";",
        "haakje openen": "(",
        "haakje sluiten": ")",
        "verwijder dat": DELETE, "verwijderen": DELETE, "ongedaan maken": DELETE,
    },
    "pl": {
        "nowa linia": "\n", "nowy wiersz": "\n",
        "nowy akapit": "\n\n",
        "kropka": ".",
        "przecinek": ",",
        "znak zapytania": "?",
        "wykrzyknik": "!",
        "dwukropek": ":",
        "średnik": ";",
        "otwórz nawias": "(",
        "zamknij nawias": ")",
        "usuń to": DELETE, "usuń": DELETE, "cofnij": DELETE,
    },
    "ru": {
        "новая строка": "\n", "с новой строки": "\n",
        "новый абзац": "\n\n",
        "точка": ".",
        "запятая": ",",
        "вопросительный знак": "?",
        "восклицательный знак": "!",
        "двоеточие": ":",
        "точка с запятой": ";",
        "открыть скобку": "(",
        "закрыть скобку": ")",
        "удалить это": DELETE, "удалить": DELETE, "отменить": DELETE,
    },
    "ar": {
        "سطر جديد": "\n",
        "فقرة جديدة": "\n\n",
        "نقطة": ".",
        "فاصلة": "،",
        "علامة استفهام": "؟",
        "علامة تعجب": "!",
        "نقطتان": ":",
        "فاصلة منقوطة": "؛",
        "افتح قوس": "(",
        "أغلق قوس": ")",
        "احذف ذلك": DELETE, "احذف": DELETE, "تراجع": DELETE,
    },
    "tr": {
        "yeni satır": "\n",
        "yeni paragraf": "\n\n",
        "nokta": ".",
        "virgül": ",",
        "soru işareti": "?",
        "ünlem işareti": "!",
        "iki nokta üst üste": ":", "iki nokta": ":",
        "noktalı virgül": ";",
        "parantez aç": "(",
        "parantez kapat": ")",
        "bunu sil": DELETE, "sil": DELETE, "geri al": DELETE,
    },
    "sv": {
        "ny rad": "\n",
        "nytt stycke": "\n\n",
        "punkt": ".",
        "komma": ",",
        "frågetecken": "?",
        "utropstecken": "!",
        "kolon": ":",
        "semikolon": ";",
        "öppna parentes": "(",
        "stäng parentes": ")",
        "radera det": DELETE, "radera": DELETE, "ångra": DELETE,
    },
    "da": {
        "ny linje": "\n",
        "nyt afsnit": "\n\n",
        "punktum": ".",
        "komma": ",",
        "spørgsmålstegn": "?",
        "udråbstegn": "!",
        "kolon": ":",
        "semikolon": ";",
        "start parentes": "(",
        "slut parentes": ")",
        "slet det": DELETE, "slet": DELETE, "fortryd": DELETE,
    },
    "fi": {
        "uusi rivi": "\n",
        "uusi kappale": "\n\n",
        "piste": ".",
        "pilkku": ",",
        "kysymysmerkki": "?",
        "huutomerkki": "!",
        "kaksoispiste": ":",
        "puolipiste": ";",
        "sulku auki": "(",
        "sulku kiinni": ")",
        "poista tuo": DELETE, "poista": DELETE, "kumoa": DELETE,
    },
    "no": {
        "ny linje": "\n",
        "nytt avsnitt": "\n\n",
        "punktum": ".",
        "komma": ",",
        "spørsmålstegn": "?",
        "utropstegn": "!",
        "kolon": ":",
        "semikolon": ";",
        "start parentes": "(",
        "slutt parentes": ")",
        "slett det": DELETE, "slett": DELETE, "angre": DELETE,
    },
    "cs": {
        "nový řádek": "\n",
        "nový odstavec": "\n\n",
        "tečka": ".",
        "čárka": ",",
        "otazník": "?",
        "vykřičník": "!",
        "dvojtečka": ":",
        "středník": ";",
        "otevřít závorku": "(", "levá závorka": "(",
        "zavřít závorku": ")", "pravá závorka": ")",
        "smaž to": DELETE, "smazat": DELETE, "zpět": DELETE,
    },
    "hu": {
        "új sor": "\n",
        "új bekezdés": "\n\n",
        "pont": ".",
        "vessző": ",",
        "kérdőjel": "?",
        "felkiáltójel": "!",
        "kettőspont": ":",
        "pontosvessző": ";",
        "nyitó zárójel": "(",
        "záró zárójel": ")",
        "töröld": DELETE, "törlés": DELETE, "visszavonás": DELETE,
    },
}

# Punctuation Whisper puts around a phrase, removed before matching
_EDGE = " .!?,;:…\"'«»“”„。．！？、，；：؟،؛"


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text).casefold()
    t = t.replace("’", "'").replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip(_EDGE)


_LOOKUP = {lang: {_normalize(k): v for k, v in table.items()}
           for lang, table in _COMMANDS.items()}


def process_commands(text: str, language: str = "en") -> CommandResult:
    """
    Check text for voice commands and return the appropriate action.
    Commands are only recognised when the entire utterance matches, so a
    sentence that merely starts with a command word ("Period pain…",
    "Löschen Sie…", "Scratch that itch…") is typed as dictated and never
    deletes anything.
    """
    commands = _LOOKUP.get(language, _LOOKUP["en"])
    replacement = commands.get(_normalize(text))
    if replacement is None:
        return CommandResult(text=text)
    if replacement == DELETE:
        return CommandResult(text="", delete_last=True, action="delete")
    return CommandResult(text=replacement)


def commands_for(language: str) -> list[tuple[str, list[str]]]:
    """[(replacement_or_DELETE, [phrases...])] in table order, for the help dialog."""
    grouped: dict[str, list[str]] = {}
    for phrase, out in _COMMANDS.get(language, _COMMANDS["en"]).items():
        grouped.setdefault(out, []).append(phrase)
    return list(grouped.items())


# ── How a command's output joins the text typed before it ─────────────────

_FULL_WIDTH = set("。、，？！：；（）")
_SENTENCE_PUNCT = set(".,?!:;。、，？！：；،؟؛")


@dataclass
class Spacing:
    attach: bool          # remove the space typed after the previous phrase
    space_after: bool     # may be followed by the usual trailing space
    replaces_punct: bool  # replaces punctuation Whisper put at the end of the previous phrase


def command_spacing(text: str) -> Spacing | None:
    """Spacing rule for a command's output, None for ordinary dictated text."""
    if text in ("\n", "\n\n"):
        return Spacing(attach=True, space_after=False, replaces_punct=False)
    if text in ("(", "（"):
        return Spacing(attach=False, space_after=False, replaces_punct=False)
    if text in (")", "）"):
        return Spacing(attach=True, space_after=text == ")", replaces_punct=False)
    if len(text) == 1 and text in _SENTENCE_PUNCT:
        return Spacing(attach=True, space_after=text not in _FULL_WIDTH, replaces_punct=True)
    return None


def ends_with_punct(text: str) -> bool:
    return bool(text) and text[-1] in _SENTENCE_PUNCT


def join_phrases(parts: list[str]) -> str:
    """Join a session's phrases as they were typed, for the history."""
    out = ""
    for part in parts:
        rule = command_spacing(part)
        if rule is None:
            joined = not out or out.endswith(("\n", "(")) or out[-1] in _FULL_WIDTH
            out += ("" if joined else " ") + part
        else:
            if rule.replaces_punct and ends_with_punct(out):
                out = out[:-1]
            out = out.rstrip(" ") + part if rule.attach else out + ("" if not out or out.endswith("\n") else " ") + part
    return out
