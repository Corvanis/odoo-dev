# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    def _get_fiscal_country_codes(self):
        return ','.join(self.env.companies.mapped('account_fiscal_country_id.code'))

    display_rounding_warning = fields.Boolean(string="Display Rounding Warning", compute='_compute_display_rounding_warning',
        help="The warning informs a rounding factor change might be dangerous on res.currency's form view.")
    fiscal_country_codes = fields.Char(store=False, default=_get_fiscal_country_codes)

    @api.depends('rounding')
    def _compute_display_rounding_warning(self):
        for record in self:
            record.display_rounding_warning = (
                record._origin.id and record._origin.rounding != record.rounding
            )

    def write(self, vals):
        if 'rounding' in vals:
            rounding_val = vals['rounding']
            for record in self:
                if (rounding_val > record.rounding or rounding_val == 0) and record._has_accounting_entries():
                    raise UserError(_("You cannot reduce the number of decimal places of a currency which has already been used to make accounting entries."))

        return super().write(vals)

    def _has_accounting_entries(self):
        """ Returns True iff this currency has been used to generate (hence, round)
        some move lines (either as their foreign currency, or as the main currency).
        """
        self.ensure_one()
        return bool(self.env['account.move.line'].sudo().search_count(['|', ('currency_id', '=', self.id), ('company_currency_id', '=', self.id)]))

    def _get_raw_rates(self, companies, date_from, date_to):
        before = Domain.custom(to_sql=lambda table: SQL("%s <= date.date", table.name))
        company_match = Domain.custom(to_sql=lambda table: SQL("%s = target_root_company.id", table.company_id))
        company_null = Domain.custom(to_sql=lambda table: SQL("%s IS NULL", table.company_id))
        target_currency = Domain.custom(to_sql=lambda table: SQL("%s = target_company.currency_id", table.currency_id))
        source_currency = Domain.custom(to_sql=lambda table: SQL("%s = source_company.currency_id", table.currency_id))
        CurrencyRate = self.env['res.currency.rate'].sudo()
        return self.env.execute_query(SQL(
            """
                SELECT source_company.id,
                       date.date,
                       %(target_rate)s / %(source_rate)s AS rate
                  FROM (SELECT generate_series(%(date_from)s::timestamp, %(date_to)s::timestamp, '1 day')::date AS date) AS date,
                       res_company source_company,
                       res_company target_company
                  JOIN res_company target_root_company ON target_root_company.id = SPLIT_PART(target_company.parent_path, '/', 1)::int
                 WHERE target_company.id = %(main_company)s
                   AND source_company.id = ANY(%(other_companies)s)
            """,
            target_rate=SQL(
                "COALESCE(%s, %s, %s, %s, 1)",
                CurrencyRate._search(before & company_match & target_currency, order='name DESC', limit=1).subselect('rate'),
                CurrencyRate._search(before & company_null & target_currency, order='name DESC', limit=1).subselect('rate'),
                CurrencyRate._search(company_match & target_currency, order='name ASC', limit=1).subselect('rate'),
                CurrencyRate._search(company_null & target_currency, order='name ASC', limit=1).subselect('rate'),
            ),
            source_rate=SQL(
                "COALESCE(%s, %s, %s, %s, 1)",
                CurrencyRate._search(before & company_match & source_currency, order='name DESC', limit=1).subselect('rate'),
                CurrencyRate._search(before & company_null & source_currency, order='name DESC', limit=1).subselect('rate'),
                CurrencyRate._search(company_match & source_currency, order='name ASC', limit=1).subselect('rate'),
                CurrencyRate._search(company_null & source_currency, order='name ASC', limit=1).subselect('rate'),
            ),
            main_company=self.env.company.id,
            other_companies=companies.ids,
            date_from=date_from,
            date_to=date_to,
        ))

    def _get_parsed_rates(self, companies, date_from, date_to, current_date=None):
        """ Get the rates converting the amounts of `companies` into the currency of the current company.

            :param date_from: start of the report period, None if unbounded.
            :param date_to: end of the report period.
            :param current_date: date of the closing rate, if different from `date_to`.
            :return: a tuple (historical, cta_intervals, current) where
                     * `historical` is {company_id: {date: rate}} over the report period (CTA only);
                     * `cta_intervals` is {company_id: [(date_from, date_to, average, retained)]} (CTA only);
                     * `current` is {company_id: rate}, the closing rate at `current_date`.
        """
        currency_translation = self.env.context.get('currency_translation', 'current')
        parsed_key, date_from, date_to, current_date, first_date, has_retained = self._get_parsed_rates_key(
            companies, date_from, date_to, current_date,
        )
        parsed_cache = self.env.cr.cache.setdefault('res_currency_parsed_rates', {})
        if parsed_key in parsed_cache:
            return parsed_cache[parsed_key]

        # Unbounded periods and retained earnings need an average rate per fiscal year.
        split_on_fiscalyears = currency_translation == 'cta' and (not date_from or has_retained)

        if currency_translation == 'current':
            fetch_from = fetch_to = window_start = current_date
        else:
            fetch_from = min(first_date, date_from or first_date, date_to, current_date)
            fetch_to = max(date_to, current_date)
            window_start = min(date_from or first_date, date_to)
            if split_on_fiscalyears:
                window_start = self._get_fiscalyears_window_start(companies, first_date, date_from, window_start)
                fetch_from = min(fetch_from, window_start)

        # raw_cache: {(target_company_id, companies): (min_date, max_date, {company_id: {date: rate}}, cumulated)}
        # Extended on either end as needed to avoid redundant DB queries.
        raw_cache = self.env.cr.cache.setdefault('res_currency_to_company_rates', {})
        raw_key = (self.env.company.id, companies)
        cached_min, cached_max, historical, cumulated = raw_cache.get(raw_key, (None, None, {}, {}))
        new_min, new_max = cached_min, cached_max

        if cached_min is None:
            for company_id, rate_date, rate in self._get_raw_rates(companies, fetch_from, fetch_to):
                historical.setdefault(company_id, {})[str(rate_date)] = rate
            new_min, new_max = fetch_from, fetch_to
        else:
            if fetch_from < cached_min:
                for company_id, rate_date, rate in self._get_raw_rates(companies, fetch_from, cached_min):
                    historical.setdefault(company_id, {})[str(rate_date)] = rate
                new_min = fetch_from
            if fetch_to > cached_max:
                for company_id, rate_date, rate in self._get_raw_rates(companies, cached_max, fetch_to):
                    historical.setdefault(company_id, {})[str(rate_date)] = rate
                new_max = fetch_to

        if new_min != cached_min or new_max != cached_max:
            cumulated = self._get_cumulated_rates(historical, new_min)
            raw_cache[raw_key] = (new_min, new_max, historical, cumulated)

        current = {company_id: date2rate[current_date] for company_id, date2rate in historical.items()}
        window_historical, cta_intervals = {}, {}
        if currency_translation == 'cta':
            cta_intervals = self._get_cta_rate_intervals(companies, cumulated, window_start, date_from, date_to, split_on_fiscalyears)
            window_historical = {
                company_id: {rate_date: rate for rate_date, rate in date2rate.items() if (date_from or rate_date) <= rate_date <= date_to}
                for company_id, date2rate in historical.items()
            }

        parsed_cache[parsed_key] = (window_historical, cta_intervals, current)
        return parsed_cache[parsed_key]

    def _get_parsed_rates_key(self, companies, date_from, date_to, current_date):
        """ Normalize the dates of a rate lookup and build the key under which its result is cached.

            The key also holds the date of the first entry and the existence of retained earnings accounts,
            as the fiscal year split depends on them and they may change within the transaction.

            :return: a tuple (key, date_from, date_to, current_date, first_date, has_retained).
        """
        currency_translation = self.env.context.get('currency_translation', 'current')
        date_from = str(date_from) if date_from else None
        date_to = str(date_to) if date_to else None
        current_date = str(current_date) if current_date else None
        if not date_to:
            date_to = current_date or str(fields.Date.context_today(self))
        if not current_date:
            current_date = date_to

        first_date, has_retained = None, False
        if currency_translation != 'current':
            first_date = str(self.env['account.move']._first_date())
            has_retained = currency_translation == 'cta' and self._has_retained_earnings_accounts()

        key = (self.env.company.id, companies, currency_translation, date_from, date_to, current_date, first_date, has_retained)
        return key, date_from, date_to, current_date, first_date, has_retained

    def _get_consolidation_rate_tables(self, companies, date_from, date_to, current_date=None):
        """ Return the (historical, cta_intervals, current) tables to join to a query, the first two
            being only built for a CTA. Cached as a report runs many queries over the same rates.
        """
        currency_translation = self.env.context.get('currency_translation', 'current')
        tables_cache = self.env.cr.cache.setdefault('res_currency_rate_tables', {})
        tables_key = self._get_parsed_rates_key(companies, date_from, date_to, current_date)[0]
        if tables_key in tables_cache:
            return tables_cache[tables_key]

        historical, cta_intervals, current = self._get_parsed_rates(companies, date_from, date_to, current_date)
        historical_table = cta_intervals_table = None
        if currency_translation == 'cta':
            historical_table = SQL(
                """(
                    SELECT company.key::int AS company_id,
                           rate.key::date AS date,
                           rate.value::numeric AS rate
                      FROM jsonb_each(%s::jsonb) AS company,
                           jsonb_each_text(company.value) AS rate
                )""",
                json.dumps(historical),
            )
            cta_intervals_table = SQL(
                "(SELECT * FROM (VALUES %s) AS rate(company_id, date_from, date_to, average, retained))",
                SQL(', ').join([
                    SQL("(%s::int, %s::date, %s::date, %s::numeric, %s::numeric)", company_id, *interval)
                    for company_id, intervals in cta_intervals.items()
                    for interval in intervals
                ] or [SQL("(NULL::int, NULL::date, NULL::date, NULL::numeric, NULL::numeric)")]),
            )

        tables_cache[tables_key] = (
            historical_table,
            cta_intervals_table,
            SQL("(SELECT %s::jsonb AS rates)", json.dumps(current)),
        )
        return tables_cache[tables_key]

    @api.model
    def _get_fiscalyears_window_start(self, companies, first_date, date_from, window_start):
        """ Return the start of the fiscal year of the first entry for an unbounded period, or the
            one of the fiscal year preceding `date_from`, needed by retained earnings, otherwise.
        """
        custom_fiscal_years = self._prefetch_custom_fiscal_years(companies)
        starts = []
        for company in companies:
            custom_records = custom_fiscal_years[company.id]
            fiscalyear_start = self._get_fiscalyear_covering(company, custom_records, window_start)[0]
            if date_from and first_date < fiscalyear_start:
                fiscalyear_start = self._get_fiscalyear_covering(company, custom_records, self._shift_date(fiscalyear_start, -1))[0]
            starts.append(fiscalyear_start)
        return min(starts, default=window_start)

    @api.model
    def _get_cumulated_rates(self, historical, origin):
        """ Return {company_id: (origin, sums)}, `sums[i]` being the sum of the rates of the `i` days
            starting at `origin`.
        """
        cumulated = {}
        origin_date = fields.Date.to_date(origin)
        for company_id, date2rate in historical.items():
            sums = [0.0]
            for rate_date in sorted(date2rate):
                sums.append(sums[-1] + date2rate[rate_date])
            cumulated[company_id] = (origin_date, sums)
        return cumulated

    @api.model
    def _get_average_rate(self, cumulated_rates, period_from, period_to):
        origin, sums = cumulated_rates
        start = (fields.Date.to_date(period_from) - origin).days
        end = (fields.Date.to_date(period_to) - origin).days + 1
        return (sums[end] - sums[start]) / (end - start)

    def _get_cta_rate_intervals(self, companies, cumulated, window_start, date_from, date_to, split_on_fiscalyears):
        """ Return the rate intervals of the accounts not converted at the closing rate: P&L accounts use
            the average rate of their period, retained earnings the one of the previous fiscal year.
        """
        custom_fiscal_years = self._prefetch_custom_fiscal_years(companies) if split_on_fiscalyears else {}
        boundaries_cache = self.env.cr.cache.setdefault('res_currency_fiscalyear_boundaries', {})

        cta_intervals = {}
        for company in companies:
            cumulated_rates = cumulated.get(company.id)
            if not cumulated_rates:
                continue
            fiscalyear_averages = []
            if split_on_fiscalyears:
                boundaries = self._get_boundaries(company, custom_fiscal_years[company.id], window_start, date_to, boundaries_cache)
                fiscalyear_averages = self._average_rate_intervals(cumulated_rates, boundaries, window_start, date_to)
            window_averages = fiscalyear_averages if not date_from else self._average_rate_intervals(
                cumulated_rates, [(date_from, date_to)], date_from, date_to,
            )
            cta_intervals[company.id] = self._build_rate_intervals(fiscalyear_averages, window_averages, window_start, date_to)

        return cta_intervals

    @api.model
    def _has_retained_earnings_accounts(self):
        cache = self.env.cr.cache
        if 'res_currency_has_retained_earnings' not in cache:
            cache['res_currency_has_retained_earnings'] = bool(
                self.env['account.account'].sudo().with_context(active_test=False).search_count(
                    [('account_type', '=', 'equity_retained')], limit=1,
                )
            )
        return cache['res_currency_has_retained_earnings']

    @api.model
    def _average_rate_intervals(self, cumulated_rates, boundaries, window_start, window_end):
        """ Return the average rate of each period of [window_start, window_end] split on `boundaries`. """
        intervals = []
        for boundary_from, boundary_to in boundaries:
            period_from = max(boundary_from, window_start)
            period_to = min(boundary_to, window_end)
            if period_to < period_from:
                continue
            rate = self._get_average_rate(cumulated_rates, period_from, period_to)
            intervals.append({
                'date_from': period_from,
                'date_to': boundary_to,
                'rate': rate,
                'prev_rate': intervals[-1]['rate'] if intervals else rate,
            })

        return intervals

    @api.model
    def _shift_date(self, date_str, days):
        return str(fields.Date.to_date(date_str) + timedelta(days=days))

    @api.model
    def _build_rate_intervals(self, fiscalyear_averages, window_averages, window_start, window_end):
        """ Merge the fiscal year and report period averages into disjoint
            ``(date_from, date_to, average, retained)`` ranges, so that lines get their rate with a
            plain range join.
        """

        def interval_covering(intervals, date_str):
            for interval in intervals:
                if interval['date_from'] <= date_str <= interval['date_to']:
                    return interval
            return None

        cuts = {window_start}
        for interval in fiscalyear_averages:
            # The last day of a fiscal year uses its own average for retained earnings.
            cuts.update((interval['date_from'], interval['date_to'], self._shift_date(interval['date_to'], 1)))
        for interval in window_averages:
            cuts.update((interval['date_from'], self._shift_date(interval['date_to'], 1)))

        sorted_cuts = sorted(cut for cut in cuts if window_start <= cut <= window_end)
        intervals = []
        for index, range_from in enumerate(sorted_cuts):
            range_to = self._shift_date(sorted_cuts[index + 1], -1) if index + 1 < len(sorted_cuts) else window_end
            fiscalyear = interval_covering(fiscalyear_averages, range_from)
            window = interval_covering(window_averages, range_from)
            average = window['rate'] if window else None
            retained = (fiscalyear['rate'] if range_from == fiscalyear['date_to'] else fiscalyear['prev_rate']) if fiscalyear else None
            if average is None and retained is None:
                continue
            intervals.append((range_from, range_to, average, retained))

        return intervals

    @api.model
    def _get_fiscalyear_covering(self, company, custom_records, date_str):
        """ Return the (date_from, date_to) of the fiscal year of `company` containing `date_str`. """
        date_from, date_to = company._get_fiscalyear_dates_from_custom_years(fields.Date.to_date(date_str), custom_records)
        return str(date_from), str(date_to)

    @api.model
    def _get_boundaries(self, company, custom_records, window_start, window_end, boundaries_cache):
        cache_entry = boundaries_cache.setdefault(company.id, {'min': None, 'max': None, 'boundaries': []})

        def append_boundaries_covering(range_from, range_to):
            date_cursor = range_from
            while date_cursor <= range_to:
                fy_date_from, fy_date_to = self._get_fiscalyear_covering(company, custom_records, date_cursor)
                if not cache_entry['boundaries'] or cache_entry['boundaries'][-1] != (fy_date_from, fy_date_to):
                    cache_entry['boundaries'].append((fy_date_from, fy_date_to))
                date_cursor = self._shift_date(fy_date_to, 1)

        if cache_entry['min'] is None:
            append_boundaries_covering(window_start, window_end)
            cache_entry['min'], cache_entry['max'] = window_start, window_end
        else:
            if window_start < cache_entry['min']:
                cache_entry['boundaries'] = []
                append_boundaries_covering(window_start, cache_entry['max'])
                cache_entry['min'] = window_start
            if window_end > cache_entry['max']:
                append_boundaries_covering(cache_entry['max'], window_end)
                cache_entry['max'] = window_end

        return cache_entry['boundaries']

    @api.model
    def _prefetch_custom_fiscal_years(self, companies):
        return {company.id: [] for company in companies}

    @api.model
    def _invalidate_consolidation_rates(self):
        self.env.cr.cache.pop('res_currency_to_company_rates', None)
        self.env.cr.cache.pop('res_currency_parsed_rates', None)
        self.env.cr.cache.pop('res_currency_rate_tables', None)

    @api.model
    def _invalidate_retained_earnings_accounts(self):
        self.env.cr.cache.pop('res_currency_has_retained_earnings', None)

    @api.model
    def _invalidate_consolidation_fiscal_years(self):
        self.env.cr.cache.pop('res_currency_fiscalyear_boundaries', None)
        self.env.cr.cache.pop('res_currency_fiscalyear_custom_records', None)
        self.env.cr.cache.pop('res_currency_parsed_rates', None)
        self.env.cr.cache.pop('res_currency_rate_tables', None)


class ResCurrencyRate(models.Model):
    _inherit = 'res.currency.rate'

    @api.model_create_multi
    def create(self, vals_list):
        self.env['res.currency']._invalidate_consolidation_rates()
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_clear_company_rate_cache(self):
        self.env['res.currency']._invalidate_consolidation_rates()

    def write(self, vals):
        self.env['res.currency']._invalidate_consolidation_rates()
        return super().write(vals)
