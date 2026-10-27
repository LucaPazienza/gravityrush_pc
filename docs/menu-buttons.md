# Menu confirm button

The launcher's **Controls → Menu confirm button** selects Cross (X / A) or Circle (O / B).
The other face button goes back. The default is Cross, preserving existing installations.
Changes take effect on the next launch; they do not remap gameplay actions.

The setting is saved as `menu_confirm=cross` or `menu_confirm=circle` in `gravityrush.ini`.
The launcher/run.py forwards it as `GOW3_MENU_CONFIRM`. An explicit environment variable
wins; an unset or invalid value selects Cross. Direct native/legacy run.sh launches can
set `GOW3_MENU_CONFIRM=circle` explicitly.

The policy covers PS4 system parameter 1000, the PC save picker (including polled gamepad
input), text entry and Dear ImGui controller navigation. Dialog hints follow the policy.
Keyboard Enter/Escape and mouse actions in the PC dialogs are unchanged. The SDL/PS4
normal gameplay pad mapping is not modified, so jump/dodge controls are not exchanged.

## Testing

- `tests/test_services.c`: default/invalid policy, both button roles, simultaneous buttons,
  no input, and the PS4 system parameter value.
- `tests/test_menu_confirm.py`: normalization, environment override, ini round trip and
  restart recovery.
- The earlier binary proof of concept was physically controller-tested on Japanese
  CUSA00546. This source change replaces that hardcoded approach with a launch setting;
  a complete rebuilt GPU/UI runtime still needs controller regression testing.
