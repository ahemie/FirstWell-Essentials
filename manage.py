"""Beginner-friendly FirstWell Essentials launcher.

Examples:
  py manage.py serve
  py manage.py list
  py manage.py my-prices            # preview only
  py manage.py my-prices --apply    # writes after review
"""
import runpy
import sys

SCRIPTS = {
    'my-prices': 'scripts.import_shopee_my_prices',
    'my-sales': 'scripts.import_shopee_my',
    'sg-sales': 'scripts.import_shopee_sg',
    'inventory': 'scripts.import_inventory_to_supabase',
    'clinic': 'scripts.import_clinic_sales',
    'shopee-links': 'scripts.import_shopee_links',
    'variations': 'scripts.import_shopee_variations',
    'mapping-check': 'scripts.check_shopee_mapping',
    'sales-matching': 'scripts.match_shopee_sales',
    'legacy-json': 'scripts.import_to_supabase',
}

def main():
    task = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if task == 'list':
        print('FirstWell Essentials commands:')
        print('  py manage.py serve               Start Flask on port 5503')
        print('  py manage.py list                Show available commands')
        for label in SCRIPTS:
            print(f'  py manage.py {label}')
        print('\nCareful: most historical import tools write only with their own scripts.')
        print('Follow the individual script help and review before writing.')
        return
    if task == 'serve':
        from app import app
        print('Open http://127.0.0.1:5503/login')
        app.run(host='127.0.0.1', port=5503, debug=False)
        return
    if task not in SCRIPTS:
        sys.exit(f'Unknown task: {task}. Run py manage.py list')
    # Keep sys.argv flags (e.g. --apply) available to the original script.
    # The management script does not itself authorize database modifications.
    sys.argv = [SCRIPTS[task], *sys.argv[2:]]
    runpy.run_module(SCRIPTS[task],run_name='__main__')

if __name__ == '__main__':
    main()
