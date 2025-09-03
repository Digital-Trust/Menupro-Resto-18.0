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

        // 🚨 AJOUT : Surveillance des ordres flottants
        this.setupFloatingOrderMonitoring();
    },

    // 🆕 NOUVELLE MÉTHODE : Surveillance des ordres flottants
    setupFloatingOrderMonitoring() {
        // Vérifier les changements toutes les 2 secondes
        this.floatingOrderInterval = setInterval(() => {
            this.checkFloatingOrderChanges();
        }, 2000);
    },

    // 🆕 NOUVELLE MÉTHODE : Vérification des changements d'ordres flottants
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

    // 🆕 NOUVELLE MÉTHODE : Détection d'ordre flottant
    isFloatingOrder(order) {
        return order.takeaway &&
               !order.table_id &&
               order.floating_order_name &&
               (order.pos_reference?.includes('Self-Order') || order.origine === 'mobile');
    },

    // 🆕 NOUVELLE MÉTHODE : Vérification des changements
    hasFloatingOrderChanged(order) {
        // Initialisation des trackers si nécessaire
        if (order.lastFloatingChangeCount === undefined) {
            order.lastFloatingChangeCount = 0;
        }
        if (order.lastFloatingLinesLength === undefined) {
            order.lastFloatingLinesLength = 0;
        }
        if (order.lastFloatingAmount === undefined) {
            order.lastFloatingAmount = order.amount_total || 0;
        }

        // Calcul des changements
        const currentChanges = this.calculateFloatingOrderChanges(order);
        const linesChanged = order.lines.length !== order.lastFloatingLinesLength;
        const amountChanged = Math.abs((order.amount_total || 0) - order.lastFloatingAmount) > 0.01;

        return currentChanges !== order.lastFloatingChangeCount ||
               linesChanged ||
               amountChanged;
    },

    // 🆕 NOUVELLE MÉTHODE : Calcul des changements pour ordres flottants
    calculateFloatingOrderChanges(order) {
        let changes = 0;

        // Changements dans les lignes
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

        // Changements dans les attributs
        if (order.mobile_user_id && order.subscription_id) {
            changes++; // Ordre mobile = changement
        }

        return changes;
    },

    // 🆕 NOUVELLE MÉTHODE : Calcul des changements de ligne
    calculateLineChanges(line) {
        let changes = 0;

        // Quantité
        if (line.qty !== (line.lastQty || 0)) {
            changes++;
            line.lastQty = line.qty;
        }

        // Prix
        if (Math.abs(line.price_subtotal - (line.lastPrice || 0)) > 0.01) {
            changes++;
            line.lastPrice = line.price_subtotal;
        }

        // Notes
        if (line.note !== (line.lastNote || '')) {
            changes++;
            line.lastNote = line.note;
        }

        return changes;
    },

    // 🆕 NOUVELLE MÉTHODE : Mise à jour du tracking
    updateFloatingOrderChangeTracking(order) {
        order.lastFloatingChangeCount = this.calculateFloatingOrderChanges(order);
        order.lastFloatingLinesLength = order.lines.length;
        order.lastFloatingAmount = order.amount_total || 0;

        console.log(`🔔 Sonnerie déclenchée pour l'ordre flottant: ${order.floating_order_name}`);
    },

    // 🆕 NOUVELLE MÉTHODE : Notification visuelle (optionnelle)
    showFloatingOrderNotification(order) {
        // Utilisation du service de notification si disponible
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

    // 🚨 AMÉLIORATION : Méthode de nettoyage
    destroy() {
        // Nettoyer l'intervalle lors de la destruction du composant
        if (this.floatingOrderInterval) {
            clearInterval(this.floatingOrderInterval);
        }
        super.destroy();
    },

    // 🔧 CORRECTION : Fonction playSound avec UN SEUL son
    playSound(soundFile) {
        fetch(soundFile, { method: 'HEAD' })
            .then(response => {
                if (response.ok) {
                    const audio = new Audio(soundFile);
                    audio.volume = 1.0; // Volume maximum

                    // Jouer le son une seule fois
                    audio.play().catch(error => {
                        console.log('Error playing sound:', error);
                        // Fallback : essayer avec interaction utilisateur
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
    }
});