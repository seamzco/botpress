from time import sleep
import requests

from pathlib import Path
import re
from botpress_nlu_testing.bot_utils import load_tgz_bot

from botpress_nlu_testing.typings import NluResult, NluServerPredictions
from typing import Optional


class BotpressApi:
    def __init__(self, endpoint: str, bot_id: str):
        """Create the api to talk with a botpress NLU server

        Parameters
        ----------
        endpoint : str
            The url of the botpress NLU server (e.g http://localhost:3200)
        bot_id : str
            The name of the bot (arbitrary and used to keep track of the model)
        """
        self.endpoint = endpoint
        self.bot_id = bot_id
        self.model_id = ""

    def is_up(self) -> None:
        try:
            response = requests.get(
                f"{self.endpoint}/v1/info",
            )

            if response.status_code != 200:
                raise ConnectionError(
                    f"Language server is not running on {self.endpoint}"
                )

        except:
            raise ConnectionError(f"Language server is not running on {self.endpoint}")

    def get_model_for_bot(self) -> Optional[str]:
        """Get the model for the bot if one was trained before

        Returns
        -------
        Optional[str]
            If a model is found, return the model_id

        Raises
        ------
        ConnectionError
            If there is any problem with the request
        """
        self.is_up()

        response = requests.get(
            f"{self.endpoint}/v1/models/", params={"appId": self.bot_id}
        )

        if not response.json()["success"]:
            raise ConnectionError(f"Problem getting model:\n{response.text}")

        models = response.json()["models"]
        if models:
            self.model_id = models[0]
            return models[0]
        else:
            return None

    def clean(self) -> None:
        """Remove all models associated with this bot

        Raises
        ------
        ConnectionError
            If anything went wrong with the request
        """
        self.is_up()

        response = requests.post(
            "http://localhost:3200/v1/models/prune", json={"appId": self.bot_id}
        )

        if not response.json()["success"]:
            raise ConnectionError(f"Problem removing models:\n{response.text}")

    def train(self, bot_path: Path, bot_lang: Optional[str]) -> None:
        """Run prediction on an utterance

        Parameters
        ----------
        bot tgz or folder : Path
            The phrase to be run in the NLP in boptress

        Raises
        ------
        ConnectionError
            Error when Training
        """
        self.is_up()
        self.clean()

        bot_data = load_tgz_bot(bot_path, bot_lang)
        response = requests.post(
            f"{self.endpoint}/v1/train",
            json={
                "language": bot_data["bot_lang"],
                "intents": bot_data["intents"],
                "contexts": bot_data["contexts"],
                "entities": bot_data["entities"],
                "appId": self.bot_id,
            },
        )

        if not response.json()["success"]:
            raise ConnectionError(f"Cannot train:\n {response.text}")

        self.model_id = response.json()["modelId"]
        sleep(2)

        try:
            response = requests.get(
                f"{self.endpoint}/v1/train/{self.model_id}",
                params={"appId": self.bot_id},
            )
            tries = 0

            while not response.json()["session"]["status"] == "done":
                sleep(2)
                response = requests.get(
                    f"{self.endpoint}/v1/train/{self.model_id}",
                    params={"appId": self.bot_id},
                )

                tries += 1
                if tries > 50:
                    raise RuntimeError(
                        "Tried 50 times to get status done when training..."
                    )

        except KeyError as err:
            raise ConnectionError(f"Cannot train:\n KeyError {err}")

    def predict(self, utterance: str, expected: str) -> NluResult:
        """Run prediction on an utterance

        Parameters
        ----------
        utterance : str
            The phrase to be run in the NLP in boptress

        Returns
        -------
        NluResult[utterance, expected, predicted, confidence]
            The complete test results

        Raises
        ------
        ConnectionError
            When getting error when predicting
        """
        self.is_up()

        if not self.model_id:
            model = self.get_model_for_bot()
            if not model:
                raise AssertionError(f"No models were train for {self.bot_id}")

        response = requests.post(
            f"{self.endpoint}/v1/predict/{self.model_id}",
            json={"utterances": [utterance], "appId": self.bot_id},
        )

        if not response.json()["success"]:
            raise ConnectionError(f"Cannot predict:\n {response.text}")

        try:
            predictions: NluServerPredictions = response.json()["predictions"][0]
            _detected_lang = predictions["detectedLanguage"]
            _entities = predictions["entities"]
            context = predictions["contexts"][0]

            best_intent = NluResult(
                utterance=utterance,
                expected=expected,
                entities=[],
                predicted="none",
                confidence=0.01,
            )

            for intent in context["intents"]:
                if intent["confidence"] > best_intent["confidence"]:
                    best_intent = NluResult(
                        utterance=utterance,
                        expected=expected,
                        entities=intent["slots"],
                        predicted=re.sub(r"__qna__[a-z0-9\d]+_", "", intent["name"]),
                        confidence=intent["confidence"],
                    )

            return best_intent

        except KeyError as err:
            raise ConnectionError(f"Cannot predict:\n Key Error {err}")
