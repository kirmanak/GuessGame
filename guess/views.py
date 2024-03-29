import json
import logging
from concurrent.futures import TimeoutError
from os import environ
from random import choice, sample

from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.http import HttpResponse, HttpRequest
from django.shortcuts import render
from requests_futures.sessions import FuturesSession

from .models import *

logger = logging.getLogger('views')


# Create your views here.
def index(request):
    logger.debug("Index requested")
    difficulties = dict()
    for difficulty in list(Difficulty):
        difficulties[int(difficulty)] = str(difficulty)

    logger.debug("Available difficulties " + str(difficulties))

    context = {'difficulties': difficulties}
    return render(request, 'guess/index.html', context)


def game(request, difficulty: int):
    logger.debug("Game requested with difficulty " + str(difficulty))
    try:
        difficulty_enum = Difficulty(difficulty)
    except ValueError:
        logger.exception("Failed to parse difficulty")
        return send_error("Unknown difficulty", 400, request)

    answer, options = generate_game(difficulty_enum)
    logger.debug("Generated answer " + str(answer))
    logger.debug("Generated options " + str(options))
    if answer is not None and options is not None:
        return play_game(answer, options, request)
    else:
        return send_error("There are no games with such a difficulty", 404, request)


def check(request, image_id: int, answer_id: int):
    image = None
    try:
        image = Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        logger.warning("Image not found")

    result = "You are correct"
    if image is None or answer_id != image.answer_id:
        result = "You are wrong"

    difficulty = None
    try:
        difficulty = int(Answer.objects.get(id=answer_id).difficulty)
    except Answer.DoesNotExist:
        logger.warning("Answer not found")

    context = {'result': result, 'difficulty': difficulty}
    return render(request, 'guess/check.html', context)


def send_error(text: str, code: int, request: HttpRequest) -> HttpResponse:
    return render(request, 'guess/error.html', {'text': text}, status=code)


def load_images(name: str, ip: str):
    api_key = environ.get("SEARCH_API_KEY")
    engine_id = environ.get("SEARCH_ENGINE_ID")
    if api_key is None or engine_id is None:
        logger.warning("API keys were not provided")
        return

    params = {'q': name, 'key': api_key, 'cx': engine_id, 'userIp': ip, 'prettyPrint': 'false', 'safe': 'active',
              'fields': 'items/link/*', 'searchType': 'image', 'imgType': 'face'}
    received = list()
    for i in range(1, 40, 10):
        params['start'] = i

        with FuturesSession() as session:
            future = session.get("https://www.googleapis.com/customsearch/v1", params=params)
            result = future.result(5)

        if result.status_code != 200:
            logger.warning("Failed to load images " + result.text)
            break
        logger.debug("Received answer from Google " + result.text)

        parsed = json.loads(result.text)
        items = parsed['items']
        for j in range(10):
            received.append(items[j]['link'])
    return received


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def generate_game(difficulty):
    answers = Answer.objects.filter(difficulty__lte=difficulty)

    if answers:
        options = sample(list(answers), 10)
        answer = choice(options)

        return answer, options
    else:
        return None, None


def play_game(answer: Answer, options: list, request: HttpRequest) -> HttpResponse:
    logger.debug("Playing game")
    images = Image.objects.filter(answer_id=answer.id)

    if images:
        logger.debug("Images are present in DB")
        return create_game_page(request, options, images)

    logger.debug("Requesting new images")

    try:
        received_images = load_images(answer.name, get_client_ip(request))
    except TimeoutError:
        logger.exception("Failed to request data from Google")
        return send_error("No connection to Google", 502, request)

    if received_images:
        save_images(answer, received_images)
        return play_game(answer, options, request)
    else:
        logger.debug("Images not found")
        return send_error("There are no images for this person", 500, request)


def create_game_page(request: HttpRequest, options: list, images: list) -> HttpResponse:
    image = choice(images)

    buttons = dict()
    for button in list(options):
        buttons[int(button.id)] = str(button.name)

    context = {'image': image.image, 'id': image.id, 'options': buttons}
    return render(request, 'guess/game.html', context)


def handle_future(future):
    result = None
    try:
        result = future.result(5)
    except TimeoutError:
        logger.warning("Failed to load image, timeout")
    return result


def save_images(answer: Answer, received_images):
    logger.debug("Saving found images")
    with FuturesSession(max_workers=40) as session:
        futures = list(map(lambda url: session.get(url), received_images))
        responses = list(map(handle_future, futures))

    logger.debug("Images were loaded")

    for img in responses:
        if img is None or img.status_code != 200:
            continue

        img_tmp = NamedTemporaryFile(delete=True)
        img_tmp.write(img.content)
        img_tmp.flush()

        model = Image()
        model.answer = answer
        model.image.save(answer.name, File(img_tmp), save=True)
