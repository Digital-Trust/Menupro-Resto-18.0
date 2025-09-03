/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Numpad, getButtons, ZERO, DECIMAL, BACKSPACE } from "@point_of_sale/app/generic_components/numpad/numpad";
import { useService } from "@web/core/utils/hooks";

export const DEFAULT_LAST_ROW = [{ value: "-", text: "+/-", disabled: true }, ZERO, DECIMAL];

patch(Numpad.prototype, {
    get buttons() {
        let buttons;
        if (this.props.buttons) {
            buttons = [...this.props.buttons];

            const minusButtonIndex = buttons.findIndex(btn =>
                typeof btn === 'object' && btn.value === '-' && btn.text === '+/-'
            );

            if (minusButtonIndex !== -1) {
                buttons[minusButtonIndex] = {
                    ...buttons[minusButtonIndex],
                    disabled: true
                };
            }
        } else {
            buttons = getButtons(DEFAULT_LAST_ROW, [
                { value: "+10" },
                { value: "+20" },
                { value: "+50" },
                BACKSPACE,
            ]);
        }

        const backspaceButton = buttons.find(btn =>
            typeof btn === 'object' && btn.value === 'Backspace'
        );

        if (backspaceButton && this.isFloatingOrder()) {
            backspaceButton.disabled = true;
            backspaceButton.text = "🚫";
            backspaceButton.class = "numpad-backspace-disabled";
        }

        return buttons;
    },

    setup() {
        if (!this.props.onClick) {
            this.numberBuffer = useService("number_buffer");
        }

        this.onClick = (buttonValue) => {
            if (buttonValue === "Backspace" && this.isFloatingOrder()) {
                return;
            }

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
    },

    isFloatingOrder() {
        try {
            const pos = this.env.services.pos;
            if (!pos) return false;

            const currentOrder = pos.get_order();
            if (!currentOrder) return false;

            return currentOrder.takeaway &&
                   !currentOrder.table_id &&
                   currentOrder.floating_order_name;
        } catch (error) {
            console.warn("Erreur lors de la détection d'ordre flottant:", error);
            return false;
        }
    }
});