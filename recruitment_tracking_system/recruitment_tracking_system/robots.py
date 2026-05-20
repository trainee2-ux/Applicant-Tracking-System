from django.http import HttpResponse


def robots_txt(_request):
    content = "\n".join(
        [
            "User-agent: *",
            "Disallow: /admin/",
        ]
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")

