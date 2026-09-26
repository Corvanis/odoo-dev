{
    'name': 'Test ORM',
    'category': 'Hidden/Tests',
    'description': """A module to test the ORM.""",
    'depends': ['base'],
    'external_dependencies': [
        {'pypi': 'num2words', 'test': True},
        {'pypi': 'asn1crypto', 'test': True},
        {'pypi': 'psutil', 'test': True},
    ],
    'data': [
        'data/test_translated_field/test_model_data.xml',
        'data/test_access_rights_data.xml',
        'data/test_action_bindings.xml',
        'data/test_inherits.xml',
        'data/test_orm_data.xml',
        'data/test_orm_partner.xml',
        'views/test_acl.xml',
        'views/test_orm_views.xml',
        'security/ir.access.csv',
    ],
    'other_files': [
        'data/test_translated_field/test_tools.convert.csv',
    ],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
