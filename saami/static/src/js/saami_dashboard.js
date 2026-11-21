/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

class SaamiDashboard extends Component {
    static template = "saami.Dashboard";

    setup() {
        this.state = useState({
            total_active_members: 0,
            pending_applications: 0,
            total_contributions: 0.0,
            period_contributions: 0.0,
            period_registration_fees: 0.0,
            currency: "$",
            date_range: "6_months",
            start_date: null,
            end_date: null,
        });

        this._computeDates();

        onWillStart(async () => {
            await this._loadMetrics();
        });
    }

    _computeDates() {
        const today = new Date();
        const end = today.toISOString().split("T")[0];
        let start = new Date();

        if (this.state.date_range === "1_month") {
            start.setMonth(start.getMonth() - 1);
        } else if (this.state.date_range === "3_months") {
            start.setMonth(start.getMonth() - 3);
        } else if (this.state.date_range === "6_months") {
            start.setMonth(start.getMonth() - 6);
        } else if (this.state.date_range === "1_year") {
            start.setFullYear(start.getFullYear() - 1);
        }

        if (this.state.date_range !== "custom") {
            this.state.start_date = start.toISOString().split("T")[0];
            this.state.end_date = end;
        }
    }

    async _loadMetrics() {
        try {
            const data = await rpc("/saami/get_dashboard_metrics", {
                start_date: this.state.start_date,
                end_date: this.state.end_date,
            });

            this.state.total_active_members = data.total_active_members || 0;
            this.state.pending_applications = data.pending_applications || 0;
            this.state.total_contributions = data.total_contributions || 0.0;
            this.state.period_contributions = data.period_contributions || 0.0;
            this.state.period_registration_fees = data.period_registration_fees || 0.0;
            this.state.currency = data.currency || "$";
        } catch (error) {
            console.error("Failed to load Saami dashboard metrics", error);
        }
    }

    async _onDateRangeChange(ev) {
        this.state.date_range = ev.target.value;
        this._computeDates();
        await this._loadMetrics();
    }

    async _onCustomStartDateChange(ev) {
        this.state.start_date = ev.target.value;
        await this._loadMetrics();
    }

    async _onCustomEndDateChange(ev) {
        this.state.end_date = ev.target.value;
        await this._loadMetrics();
    }

    get formattedTotalContributions() {
        return (this.state.total_contributions || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    get formattedPeriodContributions() {
        return (this.state.period_contributions || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }
}

registry.category("actions").add("saami_dashboard_tag", SaamiDashboard);
