# Converter Studio for LibreOffice: the UNO component behind the "Converter Studio" menu.
#
# The menu items call `service:studio.converter.libreoffice.Commands?<command>`, which runs
# `trigger(<command>)` (XJobExecutor). Macros can run the same work without dialogs through
# `execute()` (XJob); see README.md, "From a macro". The work itself is in pythonpath/converterstudio.

import traceback

import unohelper
from com.sun.star.task import XJob, XJobExecutor

IMPLEMENTATION = "studio.converter.libreoffice.Commands"


class Commands(unohelper.Base, XJobExecutor, XJob):
    def __init__(self, ctx):
        self.ctx = ctx

    def trigger(self, command):
        try:
            from converterstudio import office

            office.Commands(self.ctx).interactive(command)
        except Exception:
            # Never let an error escape into LibreOffice; show it instead.
            _show_error(self.ctx, traceback.format_exc(limit=3))

    def execute(self, arguments):
        from converterstudio import office

        return office.Commands(self.ctx).scripted(arguments)


def _show_error(ctx, text):
    try:
        import uno

        toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        box = toolkit.createMessageBox(
            toolkit.getDesktopWindow(),
            uno.Enum("com.sun.star.awt.MessageBoxType", "ERRORBOX"),
            uno.getConstantByName("com.sun.star.awt.MessageBoxButtons.BUTTONS_OK"),
            "Converter Studio",
            text,
        )
        box.execute()
        box.dispose()
    except Exception:
        pass


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(Commands, IMPLEMENTATION, (IMPLEMENTATION,))
