import argparse
import collections
import datetime
import json
import logging
import os
import re
import time

import genanki
import requests

logging.basicConfig(
    level=logging.INFO,
)

ANKI_DECK_ID = 1988534729
ANKI_MODEL_ID = 1959455220
SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_PATH, "audio_files")
USER_INFO_URL = "https://api.wanikani.com/v2/user"
SUBJECTS_URL = "https://api.wanikani.com/v2/subjects"

REQUESTS_MADE_THIS_MINUTE = collections.defaultdict(int)

def parse_args():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "--api-token",
        required=True,
        help="A WaniKani API Token, generated here: https://www.wanikani.com/settings/personal_access_tokens"
    )
    argparser.add_argument(
        "--include-in-progress-level",
        action="store_true",
        help="If passed, vocabulary for the users current level will also be exported"
    )
    argparser.add_argument(
        "--data-directory",
        default=SCRIPT_PATH,
        help="The directory to cache data from wanikani, as well as write the output anki cards to. Defaults to %(default)s"
    )

    return argparser.parse_args()


def get_last_cached():
    last_cached_path = os.path.join(args.data_directory, "last_cached.json")
    if os.path.exists(last_cached_path):
        with open(last_cached_path, "r") as fd:
            contents = fd.read()
            if contents:
                return json.loads(contents)


def set_last_cached(data):
    with open(os.path.join(args.data_directory, "last_cached.json"), "w") as fd:
        return json.dump(data, fd, separators=(", ", ": "), indent=4)


def rate_limit(f):
    def _inner(*args, **kwargs):
        while REQUESTS_MADE_THIS_MINUTE[datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")] >= 60:
            logging.info("Rate limited; waiting for rate limiting period to finalize")
            time.sleep(60 - datetime.datetime.now().second)

        REQUESTS_MADE_THIS_MINUTE[datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")] += 1
        return f(*args, **kwargs)

    return _inner


@rate_limit
def make_request(url, data={}):
    resp = requests.get(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {args.api_token}",
        }
    )

    if resp.status_code == 429:
        time.sleep(int(resp.headers["RateLimit-Reset"]) - int(time.time()))
        return make_request(url, data=data)

    return resp


def fetch_records():
    user_info = make_request(USER_INFO_URL).json()
    max_level_granted = user_info["data"]["subscription"]["max_level_granted"]
    max_level_to_export = user_info["data"]["level"]

    if not args.include_in_progress_level:
        max_level_to_export = user_info["data"]["level"]

        if max_level_to_export <= 0:
            raise Exception("No levels completed and --include-in-progress-level not passed")

    vocab_by_id = get_last_cached() or dict()
    last_id = None
    logging.info("Fetching Subjects")
    while True:
        subjects = make_request(
            SUBJECTS_URL,
            data={
                "levels": ",".join([str(lvl) for lvl in range(1, max_level_to_export + 1)]),
                "types": "kana_vocabulary,vocabulary",
                "hidden": "false",
                **({"page_after_id": last_id} if last_id else {}),
            },
        ).json()
        if not subjects['data']:
            break

        last_id = subjects['data'][-1]["id"]
        for vocab in subjects["data"]:
            vocab_by_id[vocab['id']] = vocab

    set_last_cached(vocab_by_id)

    os.makedirs(AUDIO_DIR, exist_ok=True)
    logging.info("Fetching Subject audio; this may take a while")
    for vocab_id, vocab_data in vocab_by_id.items():
        audio_name = f"wbvocab-{vocab_id}.mp3"
        if not os.path.exists(os.path.join(AUDIO_DIR, audio_name)):
            audio_url = None
            for audio_data in vocab_data['data'].get("pronunciation_audios", []):
                if audio_data["content_type"] == "audio/mpeg":
                    audio_url = audio_data["url"]
                    break

            if audio_url:
                logging.info("Fetching audio for %s", vocab_id)
                mp3 = make_request(audio_url).content
                with open(os.path.join(AUDIO_DIR, audio_name), 'w+b') as fd:
                    fd.write(mp3)

    return vocab_by_id


def gen_apkg(vocab_dict):
    logging.info("Generating Anki Deck")

    deck = genanki.Deck(
        ANKI_DECK_ID,
        "WaniKani Audio Cards"
    )
    package = genanki.Package(deck)
    model = genanki.Model(
        ANKI_MODEL_ID,
        "WaniVocab Audio Model",
        fields=[
            {"name": "Audio"},
            {"name": "Readings"},
            {"name": "PartOfSpeech"},
            {"name": "Meanings"},
            {"name": "MeaningLong"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": '<div class="audio">{{Audio}}</div>',
                "afmt": "<h1>{{Readings}}</h1>"
                        '<div>Meanings:<br><div class="meanings">{{Meanings}}</div></div>'
                        "<p>Part of Speech: <b>{{PartOfSpeech}}</b></p>"
                        "<hr>"
                        "<p>{{MeaningLong}}</p>"
            }
        ],
        css="""
        .card {
            font-size: 13px;
        }
        .audio {
          text-align: center;
        }
        .meanings {
            font-size: 16px;
            margin-left: 20px;
        }
        kanji {
            background-color: pink;
            color: black;
        }
        vocabulary {
            background-color: purple;
        }
        """
    )

    for vocab_id, vocab_data in vocab_dict.items():
        note = genanki.Note(
            model=model,
            fields=[
                f"[sound:wbvocab-{vocab_id}.mp3]",
                "<br>".join([f"<span>{r['reading']}</span>" for r in vocab_data["data"].get("readings", [])]),
                ", ".join([pos for pos in vocab_data["data"].get("parts_of_speech", [])]),
                "<br>".join([f"<span>{m['meaning']}</span>" for m in vocab_data["data"].get("meanings", []) + vocab_data["data"].get("auxiliary_meanings", [])]),
                vocab_data["data"]["meaning_mnemonic"],
            ]
        )
        deck.add_note(note)

    package.media_files = [os.path.join(AUDIO_DIR, audio_file) for audio_file in os.listdir(AUDIO_DIR)]
    package.write_to_file(os.path.join(SCRIPT_PATH, "wanikani_vocab.apkg"))


def main():
    global args

    args = parse_args()

    vocab_dict = fetch_records()
    gen_apkg(vocab_dict)
    logging.info("Done")


if __name__ == "__main__":
    main()
