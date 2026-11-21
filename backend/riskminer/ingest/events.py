"""Deterministic risk events from structured BZP fields (PLAN §6.4; catalogue/wod-kan/event_types.yaml).
origin=CALC (rule over SOURCE fields), review_status=auto, evidence_state=POTWIERDZONO, one evidence row per
event pointing at the notice + field code. Idempotent via risk_event.key. AI events are produced elsewhere."""
from __future__ import annotations

# The evidence field code is the field the quote (`cause`) comes from: change reason 5.4.4 (performance block) /
# 5.3 (change notice), cancellation justification 5.2.1 (legal basis 5.2 when there is no justification).
RULES: list[tuple[str, str, str]] = [
    # (event_type, catalogue_code, SQL producing: key, procedure_id, contract_id, change_id, summary, cause,
    #  impact_days, impact_value, impact_pct, occurred_on, source_id, notice_id, field_code)
    ("EV_LATE_COMPLETION", None, """
     SELECT 'EV_LATE_COMPLETION|pf|' || pf.id, pf.procedure_id, pf.contract_id, NULL::bigint,
            'Wykonanie po pierwotnym terminie' || CASE WHEN pf.delay_days > 0 THEN ' (+' || pf.delay_days || ' dni)' ELSE '' END,
            NULL, CASE WHEN pf.delay_days > 0 THEN pf.delay_days END, NULL::numeric, NULL::float, pf.completed_on,
            pf.source_id, pf.notice_id, '5.3'
     FROM contract_performance pf WHERE NOT pf.is_duplicate AND (pf.on_time_declared IS FALSE)"""),
    ("EV_PRICE_INCREASE", None, """
     SELECT 'EV_PRICE_INCREASE|pf|' || pf.id, pf.procedure_id, pf.contract_id, NULL, 'Wypłata wyższa niż wartość umowy ('
            || round(pf.cost_dev_pct::numeric, 1) || '%)', NULL, NULL,
            pf.total_paid_amount - pf.contract_value_amount, pf.cost_dev_pct, pf.completed_on, pf.source_id, pf.notice_id, '5.5'
     FROM contract_performance pf WHERE NOT pf.is_duplicate AND pf.cost_dev_pct > 0.1"""),
    ("EV_PAID_BELOW_CONTRACT", None, """
     SELECT 'EV_PAID_BELOW_CONTRACT|pf|' || pf.id, pf.procedure_id, pf.contract_id, NULL, 'Wypłata niższa niż wartość umowy ('
            || round(pf.cost_dev_pct::numeric, 1) || '%)', NULL, NULL,
            pf.total_paid_amount - pf.contract_value_amount, pf.cost_dev_pct, pf.completed_on, pf.source_id, pf.notice_id, '5.5'
     FROM contract_performance pf WHERE NOT pf.is_duplicate AND pf.cost_dev_pct < -1"""),
    ("EV_NOT_PERFORMED", "R12.1", """
     SELECT 'EV_NOT_PERFORMED|pf|' || pf.id, pf.procedure_id, pf.contract_id, NULL, 'Umowa niewykonana',
            pf.not_executed_reason, NULL, NULL, NULL, pf.completed_on, pf.source_id, pf.notice_id, '5.1'
     FROM contract_performance pf WHERE NOT pf.is_duplicate AND pf.executed IS FALSE"""),
    ("EV_IMPROPER_PERFORMANCE", None, """
     SELECT 'EV_IMPROPER_PERFORMANCE|pf|' || pf.id, pf.procedure_id, pf.contract_id, NULL, 'Nienależyte wykonanie umowy',
            pf.improper_reason, NULL, NULL, NULL, pf.completed_on, pf.source_id, pf.notice_id, '5.6'
     FROM contract_performance pf WHERE NOT pf.is_duplicate AND pf.properly_performed IS FALSE"""),
    ("EV_ADDITIONAL_WORKS", "R07", """
     SELECT 'EV_ADDITIONAL_WORKS|ch|' || ch.id, ch.procedure_id, ch.contract_id, ch.id,
            'Zmiana umowy: roboty dodatkowe (art. 455 ust. 1 pkt 3)', ch.cause_text, ch.delta_days, ch.delta_value_amount,
            ch.delta_value_pct, ch.changed_on, ch.source_id, ch.notice_id, CASE WHEN ch.kind = 'performance_block' THEN '5.4.4' ELSE '5.3' END
     FROM contract_change ch WHERE '455.1.3' = ANY(ch.legal_basis) AND ch.kind IN ('change_notice', 'performance_block')"""),
    ("EV_UNFORESEEN_CHANGE", "R07", """
     SELECT 'EV_UNFORESEEN_CHANGE|ch|' || ch.id, ch.procedure_id, ch.contract_id, ch.id,
            'Zmiana umowy: okoliczności nieprzewidywalne (art. 455 ust. 1 pkt 4)', ch.cause_text, ch.delta_days,
            ch.delta_value_amount, ch.delta_value_pct, ch.changed_on, ch.source_id, ch.notice_id, CASE WHEN ch.kind = 'performance_block' THEN '5.4.4' ELSE '5.3' END
     FROM contract_change ch WHERE '455.1.4' = ANY(ch.legal_basis) AND ch.kind IN ('change_notice', 'performance_block')"""),
    ("EV_TERM_EXTENSION", "R06", """
     SELECT 'EV_TERM_EXTENSION|ch|' || ch.id, ch.procedure_id, ch.contract_id, ch.id,
            'Zmiana terminu wykonania' || CASE WHEN ch.delta_days > 0 THEN ' (+' || round(ch.delta_days) || ' dni)' ELSE '' END,
            ch.cause_text, ch.delta_days, NULL, NULL, ch.changed_on, ch.source_id, ch.notice_id, CASE WHEN ch.kind = 'performance_block' THEN '5.4.4' ELSE '5.3' END
     FROM contract_change ch WHERE 'time' = ANY(ch.change_types) AND ch.kind IN ('change_notice', 'performance_block')"""),
    ("EV_TENDER_CANCELLED_BUDGET", "R11.1", """
     SELECT 'EV_TENDER_CANCELLED_BUDGET|lot|' || l.id, l.procedure_id, NULL, NULL,
            'Unieważnienie: cena oferty przewyższa kwotę zamawiającego (art. 255 pkt 3)', l.cancel_reason, NULL, NULL, NULL,
            n.published_at::date, l.source_id, l.result_notice_id, CASE WHEN l.cancel_reason IS NOT NULL THEN '5.2.1' ELSE '5.2' END
     FROM lot l LEFT JOIN notice n ON n.id = l.result_notice_id WHERE l.cancelled AND l.cancel_basis ~ '255\\s*pkt\\.?\\s*3'"""),
    ("EV_TENDER_NO_OFFERS", "R11.2", """
     SELECT 'EV_TENDER_NO_OFFERS|lot|' || l.id, l.procedure_id, NULL, NULL, 'Unieważnienie: brak ofert (art. 255 pkt 1)',
            l.cancel_reason, NULL, NULL, NULL, n.published_at::date, l.source_id, l.result_notice_id, CASE WHEN l.cancel_reason IS NOT NULL THEN '5.2.1' ELSE '5.2' END
     FROM lot l LEFT JOIN notice n ON n.id = l.result_notice_id WHERE l.cancelled AND l.cancel_basis ~ '255\\s*pkt\\.?\\s*1\\M'"""),
    ("EV_SINGLE_OFFER", "R11.2", """
     SELECT 'EV_SINGLE_OFFER|lot|' || l.id, l.procedure_id, NULL, NULL, 'Wpłynęła jedna oferta', NULL, NULL, NULL, NULL,
            n.published_at::date, l.source_id, l.result_notice_id, '6.1'
     FROM lot l LEFT JOIN notice n ON n.id = l.result_notice_id WHERE l.n_offers = 1"""),
]


async def run(conn, rid) -> dict:
    out = {}
    async with conn.transaction():
        await conn.execute("DELETE FROM evidence WHERE claim_table = 'risk_event' AND verification = 'structured_field'")
        for ev, code, sql in RULES:
            r = await conn.execute(f"""
                INSERT INTO risk_event (key, procedure_id, contract_id, change_id, summary, cause, impact_days,
                                        impact_value_amount, impact_pct, occurred_on, source_id, event_type, catalogue_code,
                                        impact_value_currency, impact_value_vat, evidence_state, conf_data_quality,
                                        conf_link_strength, origin, review_status)
                SELECT q.*, '{ev}', {f"'{code}'" if code else 'NULL'},
                       CASE WHEN q.impact_value IS NOT NULL THEN 'PLN' END,
                       CASE WHEN q.impact_value IS NOT NULL THEN 'gross' END, 'POTWIERDZONO', 0.95, 1.0, 'CALC', 'auto'
                FROM (SELECT x.key, x.procedure_id::bigint, x.contract_id::bigint, x.change_id::bigint, x.summary,
                             x.cause::text, x.impact_days::float, x.impact_value::numeric, x.impact_pct::float,
                             x.occurred_on::date, x.source_id::bigint
                      FROM ({sql}) AS x(key, procedure_id, contract_id, change_id, summary, cause, impact_days, impact_value,
                                        impact_pct, occurred_on, source_id, notice_id, field_code)) q
                ON CONFLICT (key) DO UPDATE SET summary = EXCLUDED.summary, cause = EXCLUDED.cause,
                    impact_days = EXCLUDED.impact_days, impact_value_amount = EXCLUDED.impact_value_amount,
                    impact_pct = EXCLUDED.impact_pct, occurred_on = EXCLUDED.occurred_on, updated_at = now()""")
            out[ev] = int(r.split()[-1])
            await conn.execute(f"""
                INSERT INTO evidence (claim_table, claim_id, claim_field, source_id, notice_id, field_code, url, retrieved_at,
                                      verification, evidence_state, quote)
                SELECT 'risk_event', e.id, 'event', x.source_id::bigint, x.notice_id::bigint, x.field_code::text, n.url,
                       s.retrieved_at, 'structured_field', 'POTWIERDZONO', left(x.cause::text, 1000)
                FROM ({sql}) AS x(key, procedure_id, contract_id, change_id, summary, cause, impact_days, impact_value,
                                  impact_pct, occurred_on, source_id, notice_id, field_code)
                JOIN risk_event e ON e.key = x.key
                LEFT JOIN notice n ON n.id = x.notice_id::bigint LEFT JOIN source s ON s.id = x.source_id::bigint""")
        # attach pilot projects
        await conn.execute("""UPDATE risk_event e SET project_id = pp.project_id FROM project_procedure pp
                              WHERE pp.procedure_id = e.procedure_id AND pp.method <> 'cross_reference_related'
                                AND e.project_id IS DISTINCT FROM pp.project_id""")
    out["total"] = await conn.fetchval("SELECT count(*) FROM risk_event WHERE origin = 'CALC'")
    out["pilot"] = await conn.fetchval("SELECT count(*) FROM risk_event WHERE project_id IS NOT NULL")
    return out

