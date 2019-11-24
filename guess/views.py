import json
import logging
from os import environ
from random import choice, sample

from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.http import HttpResponse, HttpRequest
from django.shortcuts import render
from requests import get, RequestException

from .models import *

logger = logging.getLogger(__name__)


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
        return HttpResponse("Unknown difficulty", status=400)

    answer, options = generate_game(difficulty_enum)
    logger.debug("Generated answer " + str(answer))
    logger.debug("Generated options " + str(options))
    if answer is not None and options is not None:
        return play_game(answer, options, request)
    else:
        return HttpResponse("There are no games with such a difficulty", status=404)


def check(request, image_id: int, answer_id: int):
    try:
        image = Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        image = None

    if image is None or answer_id != image.answer_id:
        return HttpResponse("You are wrong")
    else:
        return HttpResponse("You are correct")


def load_images(name: str, ip: str):
    api_key = environ.get("SEARCH_API_KEY")
    engine_id = environ.get("SEARCH_ENGINE_ID")
    if api_key is None or engine_id is None:
        return

    params = {'q': name, 'key': api_key, 'cx': engine_id, 'userIp': ip, 'prettyPrint': 'false', 'safe': 'active',
              'fields': 'items/link/*', 'searchType': 'image', 'imgType': 'face'}
    received = list()
    for i in range(1, 40, 10):
        params['start'] = i
        result = get("https://www.googleapis.com/customsearch/v1", params)
        if result.status_code != 200:
            break

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
    answers = Answer.objects.filter(difficulty=difficulty)

    if answers:
        answer = choice(answers)
        options = sample(list(answers), 9)
        options.append(answer)

        return answer, options
    else:
        return None, None


def play_game(answer: Answer, options: list, request: HttpRequest) -> HttpResponse:
    logger.debug("Playing game")
    images = Image.objects.filter(answer_id=answer.id)

    if images:
        logger.debug("Images are present in DB")
        return create_game_page(request, options, images)
    else:
        logger.debug("Requesting new images")
        received_images = load_images(answer.name, get_client_ip(request))
        if received_images:
            logger.debug("Saving found images")
            save_images(answer, received_images)
            return play_game(answer, options, request)
        else:
            logger.debug("Images not found")
            return HttpResponse("There are no images for this person", status=500)


def create_game_page(request: HttpRequest, options: list, images: list) -> HttpResponse:
    image = choice(images)

    buttons = dict()
    for button in list(options):
        buttons[int(button.id)] = str(button.name)

    context = {'image': image.image, 'id': image.id, 'options': buttons}
    return render(request, 'guess/game.html', context)


def save_images(answer: Answer, received_images):
    for link in received_images:
        logger.debug("Saving " + link)
        try:
            img = get(link, timeout=5)
        except RequestException:
            logger.exception("Failed to save img")
            continue

        img_tmp = NamedTemporaryFile(delete=True)
        img_tmp.write(img.content)
        img_tmp.flush()

        logger.debug("Wrote img to disk")

        model = Image()
        model.answer = answer
        model.image.save(answer.name, File(img_tmp), save=True)
        model.save()

        logger.debug("Wrote img to DB")
