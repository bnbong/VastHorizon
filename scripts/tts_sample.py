"""읽어 주기 음성 비교 — Google Cloud TTS 음성마다 같은 글을 MP3로 만들어 들어 본다.

    python -m scripts.tts_sample --out data/cache/tts-sample
    python scripts/tts_sample.py --out <폴더>
    python -m scripts.tts_sample --voices ko-KR-Chirp3-HD-Aoede,ko-KR-Neural2-A --rate 0.95 --text "..." --out <폴더>

키는 환경변수(.env) GOOGLE_TTS_API_KEY에서 읽고, 출력하지 않는다.
vasthorizon/tts.py의 합성 함수를 바로 부른다 — 서버의 글자 수 원장 · 오디오 캐시는 건드리지 않는다.
글자 수는 Google 무료 구간에서 그대로 빠지므로, 음성 수 × 글자 수를 확인하고 실행한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python scripts/tts_sample.py 직접 실행 지원

from vasthorizon.config import get_settings, get_tts_key
from vasthorizon.tts import TtsError, synthesize_text

VOICES = "ko-KR-Chirp3-HD-Aoede,ko-KR-Chirp3-HD-Leda,ko-KR-Chirp3-HD-Kore,ko-KR-Neural2-A"
TEXT = ("안녕, 지구의 친구야. 나는 거문고자리의 베가야. 지금 네가 보는 내 빛은 25년쯤 전에 이곳을 떠나, "
        "긴 어둠을 건너 오늘 밤 네 눈에 닿았어. 네가 보낸 하루가 어땠든, 그 하루도 이 빛처럼 먼 곳까지 이어질 거야. "
        "고개를 들어 나를 찾아 줘서 정말 고마워.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voices", default=VOICES, help="쉼표로 구분한 음성 이름")
    parser.add_argument("--rate", type=float, default=get_settings().tts.speaking_rate, help="말하기 속도 (기본 [tts] speaking_rate)")
    parser.add_argument("--text", default=TEXT, help="읽을 글 (기본: 편지 느낌의 짧은 글, 약 150자)")
    parser.add_argument("--out", type=Path, required=True, help="MP3를 둘 폴더")
    args = parser.parse_args()

    key = get_tts_key()
    if not key:
        print("GOOGLE_TTS_API_KEY가 없습니다. .env에 넣거나 환경변수로 지정해 주세요.", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    voices = [v.strip() for v in args.voices.split(",") if v.strip()]
    failed = False
    for voice in voices:
        try:
            audio, chars = synthesize_text(args.text, api_key=key, voice=voice, speaking_rate=args.rate,
                                           timeout=get_settings().tts.timeout)
        except TtsError as e:                       # 메시지는 종류(HTTP 상태 · 예외 이름)만 — 키는 들어 있지 않다
            print(f"[FAIL] {voice}: {e}")
            failed = True
            continue
        path = args.out / f"{voice}.mp3"
        path.write_bytes(audio)
        print(f"[ OK ] {voice}: {chars}자 · {len(audio) / 1024:.0f} KB → {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
