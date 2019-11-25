from django.db import models
from django_enumfield import enum


class Difficulty(enum.Enum):
    EASY = 0
    NORMAL = 1
    HARD = 2


# Create your models here.
class Answer(models.Model):
    name = models.CharField(max_length=100)
    difficulty = enum.EnumField(Difficulty)

    def __str__(self):
        return '{} with difficulty {}'.format(self.name, self.difficulty)


class Image(models.Model):
    answer = models.ForeignKey(Answer, on_delete=models.CASCADE)
    image = models.ImageField(upload_to="images/")

    def __str__(self):
        return '{}, image is {}'.format(self.answer, self.image)
