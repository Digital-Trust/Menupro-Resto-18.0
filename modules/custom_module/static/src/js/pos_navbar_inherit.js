import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { TableSelector } from "@pos_restaurant/overrides/components/navbar/table_selector/table_selector";
import { _t } from "@web/core/l10n/translation";
import {
    getButtons,
    EMPTY,
    ZERO,
    BACKSPACE,
} from "@point_of_sale/app/generic_components/numpad/numpad";

patch(Navbar.prototype, {
    
    get showOrdersButton() {
        const cashier = this.pos.get_cashier();
        const userRole = cashier?._role;
        return userRole !== 'cashier';
    },
    
    get showCashInOutButton() {
        const cashier = this.pos.get_cashier();
        const userRole = cashier?._role;
        return userRole !== 'cashier';
    },

   async onClickTableTab() {
//        await this.pos.syncAllOrders();
//
//        // Get current employee and their allowed floors
//        const currentEmployee = this.pos?.cashier;
//        const allowedFloors = currentEmployee?.allowed_floor_ids || [];
//
//        const allowedFloorIds = allowedFloors
//            .map(floor => Number(floor?.id ?? floor?.data?.id))
//            .filter(id => id);
//
//        this.dialog.add(TableSelector, {
//            title: _t("Table Selector"),
//            placeholder: _t("Enter a table number"),
//            buttons: getButtons([
//                EMPTY,
//                ZERO,
//                { ...BACKSPACE, class: "o_colorlist_item_color_transparent_1" },
//            ]),
//            confirmButtonLabel: _t("Jump"),
//            getPayload: async (table_number) => {
//                const find_table = (t) => t.table_number === parseInt(table_number);
//                const table =
//                    this.pos.currentFloor?.table_ids.find(find_table) ||
//                    this.pos.models["restaurant.table"].find(find_table);
//
//                if (table) {
//                    // Check if the table's floor is in the allowed floors
//                    const tableFloorId = table.floor_id?.id ?? table.floor_id;
//
//                    if (allowedFloorIds.length > 0 && !allowedFloorIds.includes(Number(tableFloorId))) {
//                        // Show error message and prevent access
//                        this.notification.add(
//                            _t("Access denied: You don't have permission to access this table's floor."),
//                            { type: "danger" }
//                        );
//                        console.warn(`⛔ Access denied to table ${table_number} on floor ID: ${tableFloorId}`);
//                        return;
//                    }
//
//                    return this.pos.setTableFromUi(table);
//                }
//
//                const floating_order = this.pos
//                    .get_open_orders()
//                    .find((o) => o.getFloatingOrderName() === table_number);
//
//                if (floating_order) {
//                    return this.setFloatingOrder(floating_order);
//                }
//
//                if (!table && !floating_order) {
//                    // For new floating orders, we can allow them as they're not tied to a specific floor
//                    this.pos.selectedTable = null;
//                    const newOrder = this.pos.add_new_order();
//                    newOrder.floating_order_name = table_number;
//                    newOrder.setBooked(true);
//                    return this.setFloatingOrder(newOrder);
//                }
//            },
//        });
    }
    
});