/** @odoo-module */

import { FloorScreen } from "@pos_restaurant/app/floor_screen/floor_screen";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useState } from "@odoo/owl";

patch(FloorScreen.prototype, {
    setup() {
        super.setup();
        const pos = usePos();
        this.pos = pos;
        const currentEmployee = pos?.cashier;
        this.allowedFloors = currentEmployee?.allowed_floor_ids || [];

        const allowedFloorIds = this.allowedFloors
            .map(floor => Number(floor?.id ?? floor?.data?.id))
            .filter(id => id);

        const currentFloorId = pos.currentFloor?.id ?? pos.currentFloor?.data?.id;

        let floorToUse = pos.currentFloor;

        if (!allowedFloorIds.includes(currentFloorId)) {
            floorToUse = this.allowedFloors[0];
            pos.currentFloor = floorToUse;
        }

        this.state = useState({
            selectedFloorId: floorToUse?.id ?? null,
            floorHeight: "100%",
            floorWidth: "100%",
            selectedTableIds: [],
            potentialLink: null,
        });

        this.setupFloatingOrderMonitoring();
    },

    setupFloatingOrderMonitoring() {
        this.floatingOrderInterval = setInterval(() => {
            this.checkFloatingOrderChanges();
        }, 2000);
    },

    checkFloatingOrderChanges() {
        try {
            const floatingOrders = this.pos.models["pos.order"].filter(
                (order) => this.isFloatingOrder(order) && !order.finalized
            );

            for (const order of floatingOrders) {
                if (this.hasFloatingOrderChanged(order)) {
                    this.playSound('/custom_module/static/src/sounds/bell.wav');
                    this.updateFloatingOrderChangeTracking(order);

                    // Optionnel : Notification visuelle
                    this.showFloatingOrderNotification(order);
                }
            }
        } catch (error) {
            console.warn("Erreur lors de la vérification des ordres flottants:", error);
        }
    },

    isFloatingOrder(order) {
        return order.takeaway &&
               !order.table_id &&
               order.floating_order_name &&
               (order.pos_reference?.includes('Self-Order') || order.origine === 'mobile');
    },

    hasFloatingOrderChanged(order) {
        if (order.lastFloatingChangeCount === undefined) {
            order.lastFloatingChangeCount = 0;
        }
        if (order.lastFloatingLinesLength === undefined) {
            order.lastFloatingLinesLength = 0;
        }
        if (order.lastFloatingAmount === undefined) {
            order.lastFloatingAmount = order.amount_total || 0;
        }

        const currentChanges = this.calculateFloatingOrderChanges(order);
        const linesChanged = order.lines.length !== order.lastFloatingLinesLength;
        const amountChanged = Math.abs((order.amount_total || 0) - order.lastFloatingAmount) > 0.01;

        return currentChanges !== order.lastFloatingChangeCount ||
               linesChanged ||
               amountChanged;
    },

    calculateFloatingOrderChanges(order) {
        let changes = 0;

        for (const line of order.lines) {
            if (line.lastChangeCount === undefined) {
                line.lastChangeCount = 0;
            }

            const lineChanges = this.calculateLineChanges(line);
            if (lineChanges !== line.lastChangeCount) {
                changes++;
                line.lastChangeCount = lineChanges;
            }
        }

        if (order.mobile_user_id && order.subscription_id) {
            changes++;
        }

        return changes;
    },

    calculateLineChanges(line) {
        let changes = 0;

        if (line.qty !== (line.lastQty || 0)) {
            changes++;
            line.lastQty = line.qty;
        }

        if (Math.abs(line.price_subtotal - (line.lastPrice || 0)) > 0.01) {
            changes++;
            line.lastPrice = line.price_subtotal;
        }

        if (line.note !== (line.lastNote || '')) {
            changes++;
            line.lastNote = line.note;
        }

        return changes;
    },

    updateFloatingOrderChangeTracking(order) {
        order.lastFloatingChangeCount = this.calculateFloatingOrderChanges(order);
        order.lastFloatingLinesLength = order.lines.length;
        order.lastFloatingAmount = order.amount_total || 0;

    },

    showFloatingOrderNotification(order) {
        if (this.env.services.notification) {
            this.env.services.notification.add(
                `🆕 Mise à jour de l'ordre flottant: ${order.floating_order_name}`,
                3000,
                { type: "info" }
            );
        }
    },

    selectFloor(floor) {
        const floorId = floor?.id ?? floor?.data?.id ?? null;

        if (floorId === null) {
            console.warn("⚠️ Impossible de lire l'id du floor sélectionné");
            return;
        }

        const allowedFloorIds = this.allowedFloors
            .map(floor => Number(floor?.id ?? floor?.data?.id))
            .filter(id => id);

        if (!allowedFloorIds.includes(Number(floorId))) {
            console.warn(`⛔ Accès refusé à l'étage : ${floor?.name || "inconnu"}`);
            return;
        }

        this.pos.currentFloor = floor;
        this.state.selectedFloorId = Number(floorId);

        this.unselectTables();
    },

    getChangeCount(table) {
        const result = super.getChangeCount(table);
        const tableOrders = this.pos.models["pos.order"].filter(
            (o) => o.table_id?.id === table.id && !o.finalized
        );
        if (result.changes > 0 && tableOrders.length) {
            for (const order of tableOrders) {
                if (order.pos_reference?.includes('Self-Order')) {
                    if (order.lastChangeCount === undefined) {
                        order.lastChangeCount = 0;
                    }
                    if (order.lastLinesLength === undefined) {
                        order.lastLinesLength = 0;
                    }
                    if (result.changes !== order.lastChangeCount || order.lastLinesLength !== order.lines.length) {
                        if (order.table_id) {
                            this.playSound('/custom_module/static/src/sounds/bell.wav');
                            order.lastChangeCount = result.changes;
                            order.lastLinesLength = order.lines.length;
                            break;
                        }
                    }
                }
            }
        }
        return result;
    },

    destroy() {
        if (this.floatingOrderInterval) {
            clearInterval(this.floatingOrderInterval);
        }
        super.destroy();
    },

    playSound(soundFile) {
        fetch(soundFile, { method: 'HEAD' })
            .then(response => {
                if (response.ok) {
                    const audio = new Audio(soundFile);
                    audio.volume = 1.0;

                    audio.play().catch(error => {
                        document.addEventListener('click', () => {
                            audio.play().catch(err => {
                                console.log('Still cannot play sound after user interaction:', err);
                            });
                        }, { once: true });
                    });
                } else {
                    console.log(`Sound file not accessible: ${soundFile}`);
                }
            })
            .catch(error => {
                console.log('Error fetching sound file:', error);
            });
    },

    getFloorChangeCount(floor) {
        let changeCount = 0;
        if (!floor) {
            return changeCount;
        }
        const table_ids = floor.table_ids;

        for (const table of table_ids) {
            const tableChange = this.getChangeCount(table);
            if (tableChange && typeof tableChange.changes === "number") {
                changeCount += tableChange.changes;
            }
        }
        return changeCount;
    }
});