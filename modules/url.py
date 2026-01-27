import urllib


def get_clean_url(url):
    'Получить чистый URL'
    parsed_url = urllib.parse.urlparse(url)
    clean = parsed_url.scheme + '://' + parsed_url.netloc
    return clean
