import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {

    async onClickTableTab() {
//        await this.pos.syncAllOrders();
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
//                if (table) {
//                    return this.pos.setTableFromUi(table);
//                }
//                const floating_order = this.pos
//                    .get_open_orders()
//                    .find((o) => o.getFloatingOrderName() === table_number);
//                if (floating_order) {
//                    return this.setFloatingOrder(floating_order);
//                }
//                if (!table && !floating_order) {
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
