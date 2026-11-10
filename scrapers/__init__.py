from . import kaitori_wiki, kaitori_shouten, morimori, kaikyo, earth

SCRAPERS = {
    "wiki": kaitori_wiki,
    "shouten": kaitori_shouten,
    "morimori": morimori,
    "kaikyo": kaikyo,
    "earth": earth,
}

SOURCE_LABELS = {
    "wiki": "買取wiki",
    "shouten": "買取商店",
    "morimori": "森森買取",
    "kaikyo": "海峡通信",
    "earth": "爆速買取のアース",
}
