import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'run'))
from source_content import extract_spanish_card


def test_running_keeps_official_link_without_nearby_races():
    html = '<main><h1>Our race</h1><div class="markdown-text">21 km <a href="https://organizer.test/rules.pdf">Rules</a></div><h2>Nearby</h2><section>OTHER RACE</section></main>'
    text = extract_spanish_card('https://running.life/es/carrera/test', html)
    assert 'Our race' in text and '21 km' in text
    assert 'https://organizer.test/rules.pdf' in text
    assert 'OTHER RACE' not in text


def test_rock_keeps_document_address_and_excludes_related():
    html = '<h1>Race</h1><section id="section-product-showcase">Race 2027</section><section id="section-product-information">Info<a href="/rules.pdf">Descargar</a><script>NOISE</script></section><section id="section-related-products">OTHER RACE</section>'
    text = extract_spanish_card('https://web.rockthesport.com/es/event/test', html)
    assert 'https://web.rockthesport.com/rules.pdf' in text
    assert 'OTHER RACE' not in text and 'NOISE' not in text


def test_changed_source_layout_is_not_success():
    with pytest.raises(ValueError):
        extract_spanish_card('https://running.life/es/carrera/test', '<h1>Loading...</h1>')
    assert extract_spanish_card('https://portugalrunning.com/test', '<h1>Race</h1>') is None
