{
    'name': 'Bahrain - Accounting',
    'icon': '/account/static/description/l10n.png',
    'countries': ['bh'],
    'category': 'Accounting/Localizations/Account Charts',
    'description': """
This is the base module to manage the accounting chart for Bahrain in Odoo.
===========================================================================
Bahrain accounting basic charts and localization.

Activates:
 - Chart of Accounts
 - Taxes
 - Tax reports
 - Fiscal Positions
 - States
    """,
    'depends': [
        'account',
        'l10n_gcc_invoice',
    ],
    'auto_install': ['account'],
    'data': [
        'data/tax_report_full.xml',
        'data/tax_report_simplified.xml',
<<<<<<< 92da3ef72429534d54fc1191f2b2c0f30b5e3002
||||||| 78ab4fa1d72f86ec09ff97f9f5e31300555eb880
        'data/res.country.state.csv',
        'data/res_country_data.xml',
=======
        'data/res.country.state.csv',
        'data/res_country_data.xml',
        'views/report_invoice_templates.xml',
>>>>>>> a4d77eb37d2df8721bc401d077302707a26ae074
    ],
    'demo': [
        'demo/demo_company.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
