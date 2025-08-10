from django.shortcuts import render, redirect
from django.conf import settings
import os


def get_logo_url():
    """Return URL for the uploaded logo if present."""
    logo_path = os.path.join(settings.MEDIA_ROOT, 'logo.png')
    if os.path.exists(logo_path):
        return settings.MEDIA_URL + 'logo.png'
    return None
from .aws_manager_core import (
    sso_login,
    cloudfront_search,
    route53_search,
    cloudfront_search_creds,
    route53_search_creds,
)


def index(request):
    context = {'logo_url': get_logo_url()}
    return render(request, 'main/index.html', context)


def search(request):
    if 'login_type' not in request.session:
        return redirect('login')

    context = {'logo_url': get_logo_url()}
    if request.method == 'POST':
        resource = request.POST.get('resource')
        search_type = request.POST.get('search_type')
        search_value = request.POST.get('search_value')

        if request.session['login_type'] == 'sso':
            access_token = request.session.get('access_token')
            sso_region = request.session.get('sso_region')
            if not all([access_token, sso_region]):
                context['error'] = 'SSO login data missing.'
            else:
                if resource == 'cloudfront':
                    results = cloudfront_search(access_token, sso_region, search_type, search_value)
                else:
                    results = route53_search(access_token, sso_region, search_type, search_value)
                context['results'] = results
        else:
            access_key = request.session.get('access_key')
            secret_key = request.session.get('secret_key')
            session_token = request.session.get('session_token')
            if not all([access_key, secret_key]):
                context['error'] = 'Credential login data missing.'
            else:
                if resource == 'cloudfront':
                    results = cloudfront_search_creds(access_key, secret_key, session_token, search_type, search_value)
                else:
                    results = route53_search_creds(access_key, secret_key, session_token, search_type, search_value)
                context['results'] = results

    return render(request, 'main/search.html', context)


def login_view(request):
    context = {'logo_url': get_logo_url()}
    if request.method == 'POST':
        login_type = request.POST.get('login_type')
        if login_type == 'sso':
            result = sso_login()
            if not result:
                context['error'] = 'SSO login failed.'
            else:
                access_token, sso_region = result
                request.session['login_type'] = 'sso'
                request.session['access_token'] = access_token
                request.session['sso_region'] = sso_region
                return redirect('search')
        else:
            access_key = request.POST.get('access_key')
            secret_key = request.POST.get('secret_key')
            session_token = request.POST.get('session_token')
            if not access_key or not secret_key:
                context['error'] = 'Please provide credentials.'
            else:
                request.session['login_type'] = 'creds'
                request.session['access_key'] = access_key
                request.session['secret_key'] = secret_key
                request.session['session_token'] = session_token
                return redirect('search')

    return render(request, 'main/login.html', context)


def logout_view(request):
    request.session.flush()
    return redirect('login')


def upload_logo(request):
    if request.method == 'POST' and request.FILES.get('logo'):
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        logo_file = request.FILES['logo']
        with open(os.path.join(settings.MEDIA_ROOT, 'logo.png'), 'wb+') as dest:
            for chunk in logo_file.chunks():
                dest.write(chunk)
        return redirect('index')
    context = {'logo_url': get_logo_url()}
    return render(request, 'main/upload_logo.html', context)
