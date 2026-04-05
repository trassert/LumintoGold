import yaml 
_default_config = {
    "url": {
        "geoapify": "https://api.geoapify.com/v1/geocode/reverse",
        "openweathermap": "https://api.openweathermap.org/data/2.5/weather?q={city}&appid={apikey}&units=metric&lang=ru",
        "fp": "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text",
        "exchangerate": "https://v6.exchangerate-api.com/v6/{token}/latest/{currency}",
    },

    "battery_path": "/sys/class/power_supply/battery/status",
    "wait_delete": 60,
    "use_ipv6": False,
}

print(yaml.dump(
            _default_config,
            allow_unicode=True,
        ))