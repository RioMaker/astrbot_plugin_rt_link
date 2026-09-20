"""Configuration math, actual card badges and isolated changed-sync history."""
import asyncio
import copy
from pathlib import Path

import pytest
from PIL import Image

from profile_data import (BANDS, RESOURCE, bpm_band, load_configuration_catalog,
                          configuration_scores, configuration_history_payload, unique_score_rows)
from profile_image import grade_ratio, card_score_rank, render_profile_image, render_configuration_image
from profile_theme import crown_state
from rating import calculate_ai_values
from service import MemoryBindingsStore, ScoreService
from storage import ScoreDatabase, load_charts


@pytest.fixture(scope='module')
def catalog():
    charts = load_charts(RESOURCE.parent / 'charts.v1.json.gz')
    catalog = load_configuration_catalog(charts)
    assert catalog['available']
    return charts, catalog


def test_seven_bpm_boundaries_are_exclusive():
    values = [0, 100, 109.99, 110, 139.99, 140, 180, 220, 280, 330, 330.01]
    assert [bpm_band(n) for n in values] == ['ultraslow'] * 3 + ['slow'] * 2 + ['normal','fast','ultrafast','rapid','rapid','laser']


def test_theory_recomputes_from_all_perfect_catalog_charts(catalog):
    _, resource = catalog
    records = []
    for key, chart in resource['catalog'].items():
        score = {'id':key[0], 'level':key[1], 'goodCount':chart['totalNotes'], 'okCount':0,
                 'ngCount':0, 'dondafulComboCount':1}
        records.append({**score, **calculate_ai_values(chart, score)})
    data = configuration_scores(records, resource)
    assert len(data['cells']) == 116
    for cell in data['cells']:
        if cell['ceiling'] is None:
            assert cell['score'] is None and cell['reason'] == 'catalog_insufficient'
        else:
            assert cell['score'] == pytest.approx(cell['ceiling'], abs=1e-10)
    empty = configuration_scores([], resource)
    assert all(c['score'] is None for c in empty['cells'])
    assert any(c['ceiling'] is not None for c in empty['cells'])


def test_badges_use_actual_score_rank_independent_of_rating_color():
    row = {'id':1, 'level':4, 'highScore':10, 'bestScoreRank':6, 'clearCount':1,
           'fullComboCount':1, 'dondafulComboCount':1, 'rating':10, 'aiConstant':10}
    assert card_score_rank(row) == 6
    assert card_score_rank({**row, 'bestScoreRank':'6'}) == 6
    assert grade_ratio(row['rating'], row['aiConstant']) == 8
    assert crown_state(row) == 'ap'
    assert grade_ratio(None, 10) is None
    assert [grade_ratio(r, 10) for r in [0, 5, 6, 7, 8, 9, 9.5, 10]] == list(range(1, 9))
    from profile_image import TEXT_RANK_COLORS
    assert TEXT_RANK_COLORS[1] == TEXT_RANK_COLORS[2]
    duplicate = {**row, 'highScore':20, 'dondafulComboCount':0, 'bestScoreRank':5}
    combined = unique_score_rows([row, duplicate, {**row, 'level':5}])
    assert len(combined) == 2
    assert combined[0]['highScore'] == 20 and combined[0]['bestScoreRank'] == 6
    assert crown_state(combined[0]) == 'ap'


def test_sync_deduplication_and_history_identity(tmp_path, catalog):
    charts, resource = catalog
    selected = list(resource['catalog'].items())[:6]
    scores = [{'song_no':key[0], 'level':key[1], 'good_cnt':chart['totalNotes'] - 4,
               'ok_cnt':4, 'ng_cnt':0, 'full_combo_cnt':1, 'clear_cnt':1,
               'dondaful_combo_cnt':0, 'high_score':900000, 'best_score_rank':5} for key, chart in selected]
    payload = {'data':{'playedRecords':{'userid':'player1', 'server':'cn', 'scoreInfo':scores}}}
    class Client:
        def kinoko(self, *args):return copy.deepcopy(payload)
        def hiroba(self, *args):return copy.deepcopy(payload)
    async def run():
        db = ScoreDatabase(tmp_path / 'scores.db')
        svc = ScoreService(MemoryBindingsStore({'qq1':{'apikey':'tk_test', 'player_id':'player1', 'server':'cn'}}),
                           lambda _:Client(), charts=charts, score_db=db, report_dir=str(tmp_path))
        try:
            ok, error, analysis = await svc._sync('qq1')
            assert ok, error
            proof = configuration_history_payload(analysis)
            assert len(db.get_configuration_snapshots('qq1', proof)) == 1
            assert 'apikey' not in str(proof)
            await svc._sync('qq1')
            await svc.get_rating_text('qq1')
            assert len(db.get_configuration_snapshots('qq1', proof)) == 1
            assert len(db.get_rating_snapshots('qq1')) == 1
            scores[0]['good_cnt'] += 1
            scores[0]['ok_cnt'] -= 1
            _, _, newer = await svc._sync('qq1')
            history = db.get_configuration_snapshots('qq1', configuration_history_payload(newer))
            assert len(history) == 2
            for field, value in [('source','hiroba'), ('algorithmVersion','future')]:
                other = {**proof, field:value}
                assert db.get_configuration_snapshots('qq1', other) == []
            for field, value in [('playerId','player2'), ('server','jp')]:
                other = {**proof, 'meta':{**proof['meta'], field:value}}
                assert db.get_configuration_snapshots('qq1', other) == []
            assert db.get_configuration_snapshots('qq2', proof) == []
            image_ok, path = await svc.generate_configuration_image('qq1')
            assert image_ok, path
            with Image.open(path) as image:assert image.size == (1440, 5430)
            assert len(list((tmp_path / 'catalog_versions').glob('*.json.gz'))) == 2
        finally:
            db.close()
    asyncio.run(run())


def test_empty_data_and_long_titles_render_without_clipping(tmp_path):
    analysis = {'meta':{'playerId':'different-player', 'server':'jp'}, 'summary':{'rating':0}, 'records':[]}
    path = render_profile_image(analysis, tmp_path / 'empty.png')
    with Image.open(path) as image:assert image.size == (1440, 2598)
    analysis['records'] = [{'id':1, 'level':5, 'title':'超长曲目名称' * 30, 'rating':10,
                            'aiConstant':10, 'accuracy':.99999, 'dondafulComboCount':1, 'bestScoreRank':6}]
    render_profile_image(analysis, tmp_path / 'long.png')
    render_configuration_image(analysis, tmp_path / 'details.png')
    assert analysis['records'][0]['accuracy'] < 1  # Rendering never rounds scoring inputs to a full-good state.
