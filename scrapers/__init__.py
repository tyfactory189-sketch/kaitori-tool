from . import kaitori_wiki, kaitori_shouten, morimori, kaikyo

SCRAPERS = {
    "wiki": kaitori_wiki,
    "shouten": kaitori_shouten,
    "morimori": morimori,
    "kaikyo": kaikyo,
}

SOURCE_LABELS = {
    "wiki": "買取wiki",
    "shouten": "買取商店",
    "morimori": "森森買取",
    "kaikyo": "海峡通信",
}
