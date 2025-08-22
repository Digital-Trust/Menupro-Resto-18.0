/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";

function generateLocalTicketNumber() {
    const today = new Date();
    const todayString = today.toDateString();
    const lastResetDate = localStorage.getItem("pos.last_reset_date");
    let currentCounter = parseInt(localStorage.getItem("pos.ticket_number")) || 0;

    let newTicketNumber;
    if (lastResetDate !== todayString) {
        newTicketNumber = 0;
        localStorage.setItem("pos.last_reset_date", todayString);
    } else {
        newTicketNumber = currentCounter + 1;
    }

    localStorage.setItem("pos.ticket_number", newTicketNumber.toString());
    return newTicketNumber;
}

async function getTicketNumber(orderId) {
    try {
        const response = await fetch('/custom_module/ticketNumber', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: orderId }),
        });
        if (response.ok) {
            const data = await response.json();
            return data.result.ticket_number;
        }
    } catch (error) {
        console.warn("Offline mode or server error", error);
    }
    return 0;
}
patch(PosOrder.prototype, {

    async setup(vals) {
        await super.setup(vals);

        try {
            const result = await getTicketNumber(parseInt(vals.id));

            if (typeof result === "number" && result !== undefined && result !== null) {
                this.ticket_number = result;
                vals.ticket_number = result;
                localStorage.setItem("pos.ticket_number", result.toString());
            } else {
                const localTicketNumber = generateLocalTicketNumber();
                this.ticket_number = localTicketNumber;
                vals.ticket_number = localTicketNumber;
                console.warn("getTicketNumber returned undefined or invalid, using fallback");
            }
        } catch (error) {
            const fallbackNumber = generateLocalTicketNumber();
            this.ticket_number = fallbackNumber;
            vals.ticket_number = fallbackNumber;
            console.error("Error in setup ticket number, fallback to offline", error);
        }
    },

    /* This function is called after the order has been successfully sent to the preparation tool(s). */
    // @Override
    updateLastOrderChange() {

        const res = super.updateLastOrderChange();
    },

     /**
     * A wrapper around line.delete() that may potentially remove multiple orderlines.
     * In core pos, it removes the linked combo lines. In other modules, it may remove
     * other related lines, e.g. multiple reward lines in pos_loyalty module.
     * @param {Orderline} line
     * @returns {boolean} true if the line was removed, false otherwise
     */
    removeOrderline(line) {
        console.log("This =======>", this);
        const linesToRemove = line.getAllLinesInCombo();
        for (const lineToRemove of linesToRemove) {
            console.log("line to remove",lineToRemove);
            if (lineToRemove.refunded_orderline_id?.uuid in this.uiState.lineToRefund) {
                delete this.uiState.lineToRefund[lineToRemove.refunded_orderline_id.uuid];
            }

            if (this.assert_editable()) {
                const cashier_id = Number(sessionStorage.getItem(`connected_cashier_${this.config.id}`));
                const currentCashier = this.models["hr.employee"].get(cashier_id);
                try {
                     rpc("/web/dataset/call_kw/pos.order/write", {
                        model: "pos.order",
                        method: "write",
                        args: [[this.id], {
                            cashier: currentCashier.name,
                            employee_id: currentCashier.id,
                        }],
                        kwargs: {},
                    });
                } catch (error) {
                    console.error("Erreur lors de la mise à jour du cashier:", error);
                }
                const payload = {
                    full_product_name: lineToRemove.full_product_name,
                    line_id: lineToRemove.id,
                    saved_quantity: lineToRemove.saved_quantity,
                    cashier: currentCashier.name,
                    order_id: this.id,
                    date: new Date().toISOString(),
                    mobile_user_id : this.mobile_user_id,
                    subscription_id : this.subscription_id,
                    order_menupro_id : this.menupro_id,

                };
                console.log(" JSON.stringify(payload)", JSON.stringify(payload))

                fetch("http://localhost:3000/Notifications/Removed-dish/notif", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(payload),
                })
                .then((res) => res.json())
                .then((data) => {
                    console.log("Notification envoyée avec succès:", data);
                })
                .catch((err) => {
                    console.error("Erreur lors de l'envoi de la notification:", err);
                });
                lineToRemove.delete();

            }
        }

        if (!this.lines.length) {
            this.general_note = "";
        }
        console.log("finale this============>",this);
        return true;
    }


});