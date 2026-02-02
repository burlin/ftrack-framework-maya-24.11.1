# :coding: utf-8
# :copyright: Copyright (c) 2024 ftrack

import maya.cmds as cmds

cmds.evalDeferred('import ftrack_framework_maya', lp=True)

# Устанавливаем меню Mroya -> Open Task Browser для запуска Qt-броузера.
cmds.evalDeferred(
    'import mroya_maya_taskhub_launcher; mroya_maya_taskhub_launcher.install_menu()',
    lp=True,
)

# TODO: setup frame range and start and end frame
