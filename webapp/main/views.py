from django.shortcuts import render, redirect

from .aws_manager_core import (
    sso_login,
    cloudfront_search,
    route53_search,
    cloudfront_search_creds,
    route53_search_creds,
)


def index(request):
    return render(request, 'main/index.html')


def search(request):
    if 'login_type' not in request.session:
        return redirect('login')

    context = {}
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
    context = {}
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
