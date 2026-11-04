/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Menu confirm button (based on PR #4 by kanjieater). */
#ifndef RUNTIME_MENU_H
#define RUNTIME_MENU_H

#include <stdlib.h>
#include <string.h>

/* GOW3_MENU_CONFIRM=circle: Circle confirms and Cross goes back in menus and the port's dialogs,
 * as on Japanese consoles. Menus only: the gameplay buttons never change. */
static inline int menu_circle_confirm(void) {
    const char *value = getenv("GOW3_MENU_CONFIRM");
    return value && strcmp(value, "circle") == 0;
}

/* Dialog result: 0 nothing, 1 accept, 2 cancel. Keyboard Enter/Escape stay as they are. */
static inline int menu_button_result(int cross, int circle) {
    const int swapped = menu_circle_confirm();
    return (swapped ? circle : cross) ? 1 : (swapped ? cross : circle) ? 2 : 0;
}

#endif
