from django.urls import path

from . import views

urlpatterns = [
    # ex /guess/
    path('', views.index, name="index"),
    # ex /guess/2/
    path('<int:difficulty>/', views.game, name="difficulty"),
    # ex /guess/5/6/
    path('<int:image_id>/<int:answer_id>/', views.check, name="check"),
]
