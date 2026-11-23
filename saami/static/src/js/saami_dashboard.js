/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

class SaamiDashboard extends Component {
    static template = "saami.Dashboard";

    setup() {
        this.growthChartRef = useRef("growthChart");
        this.statusPieChartRef = useRef("statusPieChart");
        this.growthChart = null;
        this.statusPieChart = null;

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
            membership_growth: { months: [], new_members: [], total_members: [] },
            pending_status_breakdown: { labels: [], counts: [] },
        });

        this._computeDates();

        onWillStart(async () => {
            await this._loadMetrics();
        });

        onMounted(() => {
            this._renderCharts();
        });

        onWillUnmount(() => {
            this._destroyCharts();
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
            this.state.membership_growth = data.membership_growth || { months: [], new_members: [], total_members: [] };
            this.state.pending_status_breakdown = data.pending_status_breakdown || { labels: [], counts: [] };
            this._renderCharts();
        } catch (error) {
            console.error("Failed to load Saami dashboard metrics", error);
        }
    }

    _destroyCharts() {
        if (this.growthChart) {
            this.growthChart.destroy();
            this.growthChart = null;
        }
        if (this.statusPieChart) {
            this.statusPieChart.destroy();
            this.statusPieChart = null;
        }
    }

    _renderCharts() {
        if (typeof window.ApexCharts === "undefined") {
            return;
        }
        this._destroyCharts();

        if (this.growthChartRef.el) {
            const growth = this.state.membership_growth;
            this.growthChart = new window.ApexCharts(this.growthChartRef.el, {
                chart: {
                    type: "line",
                    height: 320,
                    toolbar: { show: false },
                    fontFamily: "inherit",
                },
                series: [
                    {
                        name: "Total Members",
                        type: "area",
                        data: growth.total_members || [],
                    },
                    {
                        name: "New Members",
                        type: "column",
                        data: growth.new_members || [],
                    },
                ],
                colors: ["#3b82f6", "#10b981"],
                stroke: {
                    width: [3, 0],
                    curve: "smooth",
                },
                fill: {
                    type: ["gradient", "solid"],
                    gradient: {
                        shadeIntensity: 1,
                        opacityFrom: 0.35,
                        opacityTo: 0.05,
                    },
                },
                plotOptions: {
                    bar: {
                        columnWidth: "42%",
                        borderRadius: 4,
                    },
                },
                xaxis: {
                    categories: growth.months || [],
                },
                yaxis: {
                    min: 0,
                    forceNiceScale: true,
                    labels: {
                        formatter: (val) => Math.round(val),
                    },
                },
                dataLabels: { enabled: false },
                legend: { position: "top", horizontalAlign: "right" },
                grid: { borderColor: "#f1f5f9" },
                noData: { text: "No membership data in selected period" },
            });
            this.growthChart.render();
        }

        if (this.statusPieChartRef.el) {
            const breakdown = this.state.pending_status_breakdown;
            const counts = breakdown.counts || [];
            const hasPending = counts.some((c) => c > 0);
            this.statusPieChart = new window.ApexCharts(this.statusPieChartRef.el, {
                chart: {
                    type: "donut",
                    height: 320,
                    fontFamily: "inherit",
                },
                series: hasPending ? counts : [],
                labels: breakdown.labels || [],
                colors: ["#94a3b8", "#f59e0b", "#3b82f6"],
                legend: { position: "bottom" },
                plotOptions: {
                    pie: {
                        donut: {
                            size: "62%",
                            labels: {
                                show: true,
                                total: {
                                    show: true,
                                    label: "Pending",
                                    formatter: () => String(this.state.pending_applications || 0),
                                },
                            },
                        },
                    },
                },
                dataLabels: {
                    enabled: true,
                    formatter: (val, opts) => opts.w.config.series[opts.seriesIndex],
                },
                noData: { text: "No pending applications" },
            });
            this.statusPieChart.render();
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
