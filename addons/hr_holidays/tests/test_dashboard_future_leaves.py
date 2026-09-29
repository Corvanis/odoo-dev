from datetime import date

from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'time_off_dashboard')
class TestDashboardFutureLeaves(TransactionCase):
    """ The dashboard subtracts the future leaves linked to an accrual plan from the balance it displays.
    The validation of the requests, the crons and every other caller must keep their behavior.

    Common setup, today is 2026-09-29:
    - accrual plan: 2 days on the 1st of each month, accrued at the start of the period
    - allocation starting on 2026-01-01: 9 accruals (January to September), so 18 days accrued today
      and then 20 days on 2026-10-01, 22 on 2026-11-01 and 24 on 2026-12-01
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.employee = cls.env['hr.employee'].create({'name': 'Accrual Employee'})
        cls.work_entry_type = cls._create_work_entry_type('Accrued Time Off', 'ACCR', allows_negative=False)
        cls.accrual_plan = cls._create_accrual_plan(cls.work_entry_type)
        # the balance of this type can go slightly negative, which changes the check done in `_check_validity`
        cls.negative_work_entry_type = cls._create_work_entry_type(
            'Accrued Time Off (negative allowed)', 'ACNEG', allows_negative=True, max_allowed_negative=1)
        cls.negative_accrual_plan = cls._create_accrual_plan(cls.negative_work_entry_type)

    @classmethod
    def _create_accrual_plan(cls, work_entry_type):
        return cls.env['hr.leave.accrual.plan'].create({
            'name': '2 days per month',
            'work_entry_type_id': work_entry_type.id,
            'accrued_gain_time': 'start',
            'transition_mode': 'immediately',
            'level_ids': [(0, 0, {
                'start_count': 0,
                'start_type': 'day',
                'added_value': 2,
                'added_value_type': 'day',
                'frequency': 'monthly',
                'first_day': '1',
            })],
        })

    @classmethod
    def _create_work_entry_type(cls, name, code, allows_negative, max_allowed_negative=0):
        # no validation, so that allocations and leaves are directly validated
        return cls.env['hr.work.entry.type'].create({
            'name': name,
            'code': code,
            'requires_allocation': True,
            'time_off_selectable': True,
            'leave_validation_type': 'no_validation',
            'allocation_validation_type': 'no_validation',
            'request_unit': 'day',
            'unit_of_measure': 'day',
            'allows_negative': allows_negative,
            'max_allowed_negative': max_allowed_negative,
        })

    def _create_allocation(self, work_entry_type=None, accrual_plan=None):
        allocation = self.env['hr.leave.allocation'].create({
            'name': 'Accrual allocation',
            'employee_id': self.employee.id,
            'work_entry_type_id': (work_entry_type or self.work_entry_type).id,
            'accrual_plan_id': (accrual_plan or self.accrual_plan).id,
            'date_from': date(2026, 1, 1),
            'number_of_days': 0,
        })
        if allocation.state != 'validate':
            allocation.action_approve()
        # update the number_of_days
        allocation._update_accrual()
        return allocation

    def _create_leave(self, request_date_from, request_date_to, work_entry_type=None, from_dashboard=False):
        return self.env['hr.leave'].with_context(from_dashboard=from_dashboard).create({
            'employee_id': self.employee.id,
            'work_entry_type_id': (work_entry_type or self.work_entry_type).id,
            'request_date_from': request_date_from,
            'request_date_to': request_date_to,
        })

    def _get_info(self, from_dashboard, target_date=None):
        """ Return the data of `self.work_entry_type` as the dashboard requests it (`from_dashboard`),
        or as any other caller (validation, cron, ...) gets it. """
        target_date = target_date or date.today()
        if from_dashboard:
            work_entry_type = self.work_entry_type.with_context(employee_id=self.employee.id, from_dashboard=True)
            data = work_entry_type.get_allocation_data_request(target_date, False)
        else:
            data = self.work_entry_type.get_allocation_data(self.employee, target_date)[self.employee]
        return next(info for _name, info, _requires_allocation, type_id in data if type_id == self.work_entry_type.id)

    @freeze_time('2026-09-29')
    def test_baseline_18_days_accrued_today(self):
        self._create_allocation()
        info = self._get_info(from_dashboard=True)
        self.assertAlmostEqual(info['max_leaves'], 18)
        self.assertAlmostEqual(info['virtual_remaining_leaves'], 18)

    @freeze_time('2026-09-29')
    def test_future_leave_is_subtracted_on_dashboard_only(self):
        """ 18 days accrued today and 2 days requested for next month: the dashboard displays 16,
        any other caller still gets 18 (the leave will be covered by the accruals of that period). """
        self._create_allocation()
        self._create_leave(date(2026, 11, 16), date(2026, 11, 17))

        dashboard = self._get_info(from_dashboard=True)
        other = self._get_info(from_dashboard=False)

        self.assertAlmostEqual(dashboard['virtual_remaining_leaves'], 16)
        self.assertAlmostEqual(dashboard['remaining_leaves'], 16)
        self.assertAlmostEqual(dashboard['leaves_approved'], 2)
        self.assertAlmostEqual(dashboard['leaves_requested'], 0)
        self.assertAlmostEqual(dashboard['max_leaves'], 18, msg="The allocated amount must not change")

        self.assertAlmostEqual(other['virtual_remaining_leaves'], 18)
        self.assertAlmostEqual(other['leaves_approved'], 0)
        self.assertAlmostEqual(other['future_accrual_leaves'], 2)

    @freeze_time('2026-09-29')
    def test_dashboard_entry_point(self):
        """ Same as above through the method called by the dashboard. """
        self._create_allocation()
        self._create_leave(date(2026, 11, 16), date(2026, 11, 17))
        employee_model = self.env['hr.employee'].with_context(employee_id=self.employee.id, from_dashboard=True)
        allocation_data = employee_model.get_time_off_dashboard_data()['allocation_data']

        info = next(info for _name, info, _requires_allocation, type_id in allocation_data
                    if type_id == self.work_entry_type.id)
        self.assertAlmostEqual(info['virtual_remaining_leaves'], 16)

    @freeze_time('2026-09-29')
    def test_dashboard_balance_can_be_negative(self):
        """ 20 days requested in the future: each request is covered by what will be accrued at its own date,
        but the dashboard displays what is left today, which is negative. """
        self._create_allocation()
        leaves = self.env['hr.leave']
        for date_from, date_to in (
            (date(2026, 11, 16), date(2026, 11, 20)),
            (date(2026, 11, 23), date(2026, 11, 27)),
            (date(2026, 12, 7), date(2026, 12, 11)),
            (date(2026, 12, 14), date(2026, 12, 18)),
        ):
            leaves |= self._create_leave(date_from, date_to)

        dashboard = self._get_info(from_dashboard=True)
        other = self._get_info(from_dashboard=False)

        self.assertEqual(set(leaves.mapped('state')), {'validate'})
        self.assertAlmostEqual(dashboard['virtual_remaining_leaves'], -2)
        self.assertAlmostEqual(other['virtual_remaining_leaves'], 18)

    @freeze_time('2026-09-29')
    def test_validation_still_blocks_when_not_enough_accrued(self):
        """ The validation of a request does not depend on the dashboard: 20 days are already planned
        and 24 will be accrued on 2026-12-21, so 5 more days must still be refused. """
        self._create_allocation()
        for date_from, date_to in (
            (date(2026, 11, 16), date(2026, 11, 20)),
            (date(2026, 11, 23), date(2026, 11, 27)),
            (date(2026, 12, 7), date(2026, 12, 11)),
            (date(2026, 12, 14), date(2026, 12, 18)),
        ):
            self._create_leave(date_from, date_to)

        with self.assertRaises(ValidationError):
            self._create_leave(date(2026, 12, 21), date(2026, 12, 25))

    @freeze_time('2026-09-29')
    def test_validation_same_result_with_dashboard_flag(self):
        """ Same as above with the dashboard key in the context. """
        self._create_allocation()
        for date_from, date_to in (
            (date(2026, 11, 16), date(2026, 11, 20)),
            (date(2026, 11, 23), date(2026, 11, 27)),
            (date(2026, 12, 7), date(2026, 12, 11)),
            (date(2026, 12, 14), date(2026, 12, 18)),
        ):
            self._create_leave(date_from, date_to)

        with self.assertRaises(ValidationError):
            self._create_leave(date(2026, 12, 21), date(2026, 12, 25), from_dashboard=True)

    @freeze_time('2026-09-29')
    def test_cancel_invalid_leaves_cron_unchanged(self):
        """ A valid leave starting in the next 31 days is not cancelled by the cron. """
        self._create_allocation()
        leave = self._create_leave(date(2026, 10, 12), date(2026, 10, 13))
        self.env['hr.leave']._cancel_invalid_leaves()
        self.assertEqual(leave.state, 'validate')

    @freeze_time('2026-09-29')
    def test_dropdown_label(self):
        """ The time type displayed when requesting a time off on 2026-10-12 (20 days accrued at that date)
        also takes into account the leave planned in November, the real balance is untouched. """
        self._create_allocation()
        self._create_leave(date(2026, 11, 16), date(2026, 11, 17))
        work_entry_type = self.work_entry_type.with_context(
            employee_id=self.employee.id, leave_date_from=date(2026, 10, 12))

        self.assertAlmostEqual(work_entry_type.max_leaves, 20)
        self.assertAlmostEqual(work_entry_type.virtual_remaining_leaves, 20)
        self.assertAlmostEqual(work_entry_type.display_virtual_remaining_leaves, 18)
        self.assertIn("18 remaining out of 20 days", work_entry_type.display_name)

    def _create_leaves_in_december_on_negative_type(self):
        # 19 days, each one valid at its own date: 24 days are accrued from 2026-12-01
        for date_from, date_to in (
            (date(2026, 12, 7), date(2026, 12, 11)),
            (date(2026, 12, 14), date(2026, 12, 18)),
            (date(2026, 12, 21), date(2026, 12, 25)),
            (date(2026, 12, 28), date(2026, 12, 31)),
        ):
            self._create_leave(date_from, date_to, work_entry_type=self.negative_work_entry_type)

    @freeze_time('2026-09-29')
    def test_negative_type_validation_without_flag(self):
        """ 5 days on 2026-11-16 are valid: 22 days are accrued at that date, even if 19 more days are planned
        in December (they are not consumed yet). Reference for the test below. """
        self._create_allocation(self.negative_work_entry_type, self.negative_accrual_plan)
        self._create_leaves_in_december_on_negative_type()
        leave = self._create_leave(
            date(2026, 11, 16), date(2026, 11, 20), work_entry_type=self.negative_work_entry_type)
        self.assertEqual(leave.state, 'validate')

    @freeze_time('2026-09-29')
    def test_negative_type_validation_ignores_dashboard_flag(self):
        """ Same request as above with the dashboard key in the context: it must still be valid.
        For a type allowing a negative balance, `_check_validity` compares the virtual remaining leaves
        with the maximum excess. If the leaves planned in December were subtracted (17 - 19 = -2 < -1),
        a valid request would be refused. """
        self._create_allocation(self.negative_work_entry_type, self.negative_accrual_plan)
        self._create_leaves_in_december_on_negative_type()
        leave = self._create_leave(
            date(2026, 11, 16), date(2026, 11, 20),
            work_entry_type=self.negative_work_entry_type, from_dashboard=True)
        self.assertEqual(leave.state, 'validate')
