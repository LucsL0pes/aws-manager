from django.shortcuts import render

from .aws_manager_core import sso_login, cloudfront_search, route53_search


def index(request):
    return render(request, 'main/index.html')


def search(request):
    context = {}
    if request.method == 'POST':
        resource = request.POST.get('resource')
        search_type = request.POST.get('search_type')
        search_value = request.POST.get('search_value')
        login_result = sso_login()
        if not login_result:
            context['error'] = 'SSO login failed.'
        else:
            access_token, sso_region = login_result
            if resource == 'cloudfront':
                results = cloudfront_search(access_token, sso_region, search_type, search_value)
            else:
                results = route53_search(access_token, sso_region, search_type, search_value)
            context['results'] = results
    return render(request, 'main/search.html', context)
