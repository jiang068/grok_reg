"""Start script for grok_reg package.

Run this file to start the project (it will call the package CLI).
"""
if __name__ == '__main__':
    # Try to import the package CLI; when this file is executed directly the
    # package may not be on sys.path, so try to fix sys.path and finally
    # fall back to executing the package __main__.py via runpy.
    import sys
    import os
    import runpy

    try:
        from grok_reg.__main__ import cli
    except Exception:
        # Ensure parent directory (workspace root) is on sys.path so that
        # `import grok_reg` works when running this file directly from
        # the package directory.
        parent = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if parent not in sys.path:
            sys.path.insert(0, parent)
        try:
            from grok_reg.__main__ import cli
        except Exception:
            # As a last resort, execute the package __main__.py as a script
            runpy.run_path(os.path.join(parent, 'grok_reg', '__main__.py'), run_name='__main__')
            sys.exit(0)

    cli()
