{
    'name': 'Cloudflare R2 Attachment Storage',
    'version': '18.0.1.0.0',
    'category': 'Technical Settings',
    'summary': 'Store media and document attachments in Cloudflare R2 while keeping web assets local',
    'author': 'Unknown',
    'license': 'LGPL-3',
    'depends': ['base', 'base_setup'],
    'external_dependencies': {
        'python': ['boto3'],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
