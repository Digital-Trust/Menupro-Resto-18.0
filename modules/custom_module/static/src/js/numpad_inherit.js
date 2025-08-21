/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Numpad, getButtons, ZERO, DECIMAL, BACKSPACE } from "@point_of_sale/app/generic_components/numpad/numpad";
import { useService } from "@web/core/utils/hooks";

export const DEFAULT_LAST_ROW = [{ value: "-", text: "+/-", disabled: true }, ZERO, DECIMAL];

patch(Numpad.prototype, {
    get buttons() {
        let buttons;
        if (this.props.buttons) {
            // Use props.buttons but modify the +/- button
            buttons = [...this.props.buttons];

           // Find and modify the +/- button
            const minusButtonIndex = buttons.findIndex(btn =>
                typeof btn === 'object' && btn.value === '-' && btn.text === '+/-'
            );

            if (minusButtonIndex !== -1) {
                // Modify the existing button to add disabled: true
                buttons[minusButtonIndex] = {
                    ...buttons[minusButtonIndex],
                    disabled: true
                };
            }
        } else {
            // Fallback to our custom configuration
            buttons = getButtons(DEFAULT_LAST_ROW, [
                { value: "+10" },
                { value: "+20" },
                { value: "+50" },
                BACKSPACE,
            ]);
        }

        return buttons;
    },

    setup() {
        if (!this.props.onClick) {
            this.numberBuffer = useService("number_buffer");
        }

        // Define our own onClick that checks the disabled property
        this.onClick = (buttonValue) => {

           // Find the clicked button
            const button = this.buttons.find(btn => {
                if (typeof btn === 'object' && 'value' in btn) {
                    return btn.value === buttonValue;
                }
                return btn === buttonValue;
            });


            if (button && typeof button === 'object' && button.disabled) {
                return;
            }

            if (this.props.onClick) {
                return this.props.onClick(buttonValue);
            } else if (this.numberBuffer) {
                return this.numberBuffer.sendKey(buttonValue);
            }
        };
    }
});