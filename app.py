"""Desktop entry point, including an offline packaged-startup diagnostic."""
import sys
from lms_app.gui import main

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        from lms_app.smoke import run
        run(sys.argv[2])
    else:
        main()
