"""Тесты чистых HTML-парсеров источников (без сети): sr57, iprice, kingstore, repremium, mobilax."""
from mvp7_price_scout.sources.iprice_source import parse_iprice
from mvp7_price_scout.sources.ispace_source import parse_offer as parse_ispace_offer
from mvp7_price_scout.sources.kingstore_source import parse_kingstore
from mvp7_price_scout.sources.mobilax_source import parse_mobilax
from mvp7_price_scout.sources.repremium_source import parse_repremium
from mvp7_price_scout.sources.sr57_source import parse_sr57

SR57_HTML = """
<ul class="products">
  <li class="product">
    <a class="woocommerce-LoopProduct-link" href="https://sr57.ru/p/iphone-17-256">link</a>
    <h2 class="woocommerce-loop-product__title">Apple iPhone 17 256Gb</h2>
    <span class="price"><span class="woocommerce-Price-amount">144 990 &#8381;</span></span>
  </li>
  <li class="product outofstock">
    <a class="woocommerce-LoopProduct-link" href="https://sr57.ru/p/iphone-16-128">link</a>
    <h2 class="woocommerce-loop-product__title">Apple iPhone 16 128Gb</h2>
    <span class="price">
      <del><span class="woocommerce-Price-amount">90 000 &#8381;</span></del>
      <ins><span class="woocommerce-Price-amount">85 000 &#8381;</span></ins>
    </span>
  </li>
</ul>
"""

IPRICE_HTML = """
<div class="js-product-item">
  <a href="/product/iphone-17-256">x</a>
  <div class="product-list__name">Apple iPhone 17 256Gb</div>
  <div class="price">151 000 руб</div>
</div>
<div class="js-product-item">
  <a href="/product/iphone-16-128">x</a>
  <div class="product-list__name">Apple iPhone 16 128Gb</div>
  <div class="price">нет в наличии</div>
</div>
"""


def test_parse_sr57_price_stock_discount():
    prods = parse_sr57(SR57_HTML)
    assert len(prods) == 2
    by_title = {p.title: p for p in prods}

    p1 = by_title["Apple iPhone 17 256Gb"]
    assert p1.shop == "sr57" and p1.price == 144990 and p1.in_stock is True
    assert p1.url == "https://sr57.ru/p/iphone-17-256"

    p2 = by_title["Apple iPhone 16 128Gb"]
    assert p2.price == 85000          # ins (цена со скидкой) приоритетнее del
    assert p2.in_stock is False       # класс outofstock


def test_parse_iprice_price_and_url_prefix():
    prods = parse_iprice(IPRICE_HTML)
    assert len(prods) == 2
    by_title = {p.title: p for p in prods}

    p1 = by_title["Apple iPhone 17 256Gb"]
    assert p1.shop == "iprice" and p1.price == 151000
    assert p1.url == "https://iprice.store/product/iphone-17-256"   # относительный -> абсолютный
    assert p1.in_stock is True

    p2 = by_title["Apple iPhone 16 128Gb"]
    assert p2.price is None            # «нет в наличии» вместо цены
    assert p2.in_stock is False


KINGSTORE_HTML = """
<div class="index-products-body-item itemRoot product-card root"
     data-id="4971" data-category="iphone"
     data-product-name="Смартфон Apple iPhone 17e 256 ГБ Белый" data-product-price="62990">
  <a class="index-products-body-item__title" href="/catalog/iphone/iphone-17e/belyy/">
    Смартфон Apple iPhone 17e 256 ГБ Белый</a>
  <div class="index-products-body-item__button-price">от 62 990 руб.</div>
</div>
<div class="index-products-body-item itemRoot product-card root"
     data-id="4972" data-category="iphone"
     data-product-name="Смартфон Apple iPhone 16 128 ГБ Черный" data-product-price="">
  <a class="index-products-body-item__title" href="/catalog/iphone/iphone-16/chernyy/">
    Смартфон Apple iPhone 16 128 ГБ Черный</a>
  <div class="index-products-body-item__button-title">Нет в наличии</div>
</div>
<div class="index-products-body-item itemRoot product-card root"
     data-id="4980" data-category="airpods"
     data-product-name="Наушники Apple AirPods Max USB-C синий" data-product-price="1">
  <a class="index-products-body-item__title" href="/catalog/airpods/max/siniy/">Max</a>
</div>
"""


def test_parse_kingstore_data_attrs():
    prods = parse_kingstore(KINGSTORE_HTML)
    assert len(prods) == 3
    by_title = {p.title: p for p in prods}

    p3 = by_title["Наушники Apple AirPods Max USB-C синий"]
    assert p3.price is None                 # data-product-price="1" -> плейсхолдер, None

    p1 = by_title["Смартфон Apple iPhone 17e 256 ГБ Белый"]
    assert p1.shop == "kingstore" and p1.price == 62990 and p1.in_stock is True
    assert p1.url == "https://oryol.kingstore.link/catalog/iphone/iphone-17e/belyy/"
    assert p1.storage == "256gb"            # объём вытащил normalize

    p2 = by_title["Смартфон Apple iPhone 16 128 ГБ Черный"]
    assert p2.price is None                 # пустой data-product-price -> None
    assert p2.in_stock is False             # «нет в наличии»


REPREMIUM_HTML = """
<div class="catalog-card2">
  <a href="/oryol/catalog/smartfon_apple_iphone_15_128_gb_siniy/">x</a>
  <div class="homepage2-products-slide__title">Смартфон Apple iPhone 15 128 ГБ синий</div>
  <div class="homepage2-products-slide-price__value">50 890 ₽</div>
</div>
<div class="catalog-card2">
  <a href="/oryol/catalog/smartfon_apple_iphone_15_128_gb_siniy_obmenka/">x</a>
  <div class="homepage2-products-slide__title">Смартфон Apple iPhone 15 128 ГБ синий</div>
  <div class="homepage2-products-slide-price__value">39 890 ₽</div>
</div>
<div class="catalog-card2">
  <a href="/oryol/catalog/smartfon_apple_iphone_15_128_gb_siniy_demo/">x</a>
  <div class="homepage2-products-slide__title">Смартфон Apple iPhone 15 128 ГБ синий</div>
  <div class="homepage2-products-slide-price__value">38 000 ₽</div>
</div>
"""


def test_parse_repremium_skips_obmen_and_demo():
    prods = parse_repremium(REPREMIUM_HTML)
    # обмен (trade-in) и demo (витрина) — мимо; остаётся только новый
    assert len(prods) == 1
    p = prods[0]
    assert p.shop == "repremium" and p.price == 50890
    assert p.url.endswith("_siniy/")           # именно новый, не обменка/demo


# Реальная разметка листинга мобилакс.рф (Webasyst Shop-Script + schema.org), сокращённая.
MOBILAX_HTML = """
<div class="products__item" itemscope itemtype="http://schema.org/Product">
  <a href="/apple-iphone-17-pro-max-256gb-cosmic-orange-novyy/">
    <div class="products__item-info">
      <span class="products__item-info-name" itemprop="name">Apple iPhone 17 Pro Max 256Gb Cosmic Orange (NEW)</span>
    </div>
  </a>
  <div class="products__bottom">
    <meta itemprop="price" content="102990">
    <div class="products__available"><div class="products__available-in-stock">Доступно</div></div>
    <div class="products__price"><div class="products__price-new">102 990 <span class="ruble">&#8381;</span></div></div>
  </div>
</div>
<div class="products__item" itemscope itemtype="http://schema.org/Product">
  <a href="/apple-iphone-16-128gb-black/">
    <div class="products__item-info">
      <span class="products__item-info-name" itemprop="name">Apple iPhone 16 128Gb Black</span></div>
  </a>
  <div class="products__bottom">
    <div class="products__available">Нет в наличии</div>
    <div class="products__price"><div class="products__price-new">64 990 <span class="ruble">&#8381;</span></div></div>
  </div>
</div>
"""


def test_parse_mobilax_price_stock_url():
    prods = parse_mobilax(MOBILAX_HTML)
    assert len(prods) == 2
    by_title = {p.title: p for p in prods}

    p1 = by_title["Apple iPhone 17 Pro Max 256Gb Cosmic Orange (NEW)"]
    assert p1.shop == "mobilax" and p1.price == 102990        # из itemprop=price (чистое целое)
    assert p1.url == "https://xn--80abvjddo3a.xn--p1ai/apple-iphone-17-pro-max-256gb-cosmic-orange-novyy/"
    assert p1.in_stock is True
    assert p1.storage == "256gb"                              # объём вытащил normalize

    p2 = by_title["Apple iPhone 16 128Gb Black"]
    assert p2.price == 64990                                  # фолбэк на .products__price-new
    assert p2.in_stock is False                               # «Нет в наличии»


# Страница товара ispace: цена в .good__total-price; блок «популярное»
# (.populars__item-price, дешёвые сопутствующие) НЕ должен подменять цену.
ISPACE_OFFER_HTML = """
<html><head><meta property="og:title" content="Apple iPhone 15 512Gb Black eSIM"></head>
<body>
  <div class="populars"><div class="populars__item-price t2">4 490 &#8381;</div></div>
  <div class="good__total-price t2">75&nbsp;890 &#8381;</div>
  <meta itemprop="price" content="75890">
</body></html>
"""


def test_parse_ispace_offer_uses_total_price_not_populars():
    p = parse_ispace_offer(
        ISPACE_OFFER_HTML,
        "https://orel.ispace-shop.ru/offers/apple_iphone_15_512gb_black_esim/")
    assert p and p.shop == "ispace"
    assert p.price == 75890                     # good__total-price, НЕ 4 490 из «популярное»
    assert "iphone 15" in p.title.lower() and p.storage == "512gb"
    assert parse_ispace_offer("", "") is None   # пустой HTML -> None (без падения)


def test_parse_empty_html_no_crash():
    assert parse_sr57("") == []
    assert parse_iprice("") == []
    assert parse_kingstore("") == []
    assert parse_repremium("") == []
    assert parse_mobilax("") == []
