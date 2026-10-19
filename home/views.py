from django.http import HttpResponse

def home(resquest):
    return HttpResponse("Hellow World : My first Django project")

def about(request):
    return HttpResponse("This is the about page")
