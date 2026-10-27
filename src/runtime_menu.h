/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef RUNTIME_MENU_H
#define RUNTIME_MENU_H

#include <stdlib.h>
#include <string.h>

/* Menu policy only. Never use this to remap the gameplay pad's face buttons.
 * Set once at launch; the launcher stores menu_confirm=cross|circle in the ini.
 * Missing/invalid values preserve the existing Cross-confirm behavior. */
static inline int menu_circle_confirm(void) {
    const char *value = getenv("GOW3_MENU_CONFIRM");
    return value && strcmp(value, "circle") == 0;
}

/* Dialog result: 0 nothing, 1 accept, 2 cancel. Keyboard handling stays separate. */
static inline int menu_button_result(int cross, int circle) {
    const int japanese = menu_circle_confirm();
    return (japanese ? circle : cross) ? 1 : (japanese ? cross : circle) ? 2 : 0;
}

#endif
