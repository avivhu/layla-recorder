#!/bin/bash
# Sleep Monitor Service Management Script

SERVICE_NAME="sleep-monitor.service"

show_status() {
    echo "=== Sleep Monitor Service Status ==="
    sudo systemctl status $SERVICE_NAME
}

start_service() {
    echo "Starting Sleep Monitor service..."
    sudo systemctl start $SERVICE_NAME
    echo "Service started!"
}

stop_service() {
    echo "Stopping Sleep Monitor service..."
    sudo systemctl stop $SERVICE_NAME
    echo "Service stopped!"
}

restart_service() {
    echo "Restarting Sleep Monitor service..."
    sudo systemctl restart $SERVICE_NAME
    echo "Service restarted!"
}

enable_service() {
    echo "Enabling Sleep Monitor service to start on boot..."
    sudo systemctl enable $SERVICE_NAME
    echo "Service enabled!"
}

disable_service() {
    echo "Disabling Sleep Monitor service from starting on boot..."
    sudo systemctl disable $SERVICE_NAME
    echo "Service disabled!"
}

show_logs() {
    echo "=== Sleep Monitor Service Logs ==="
    sudo journalctl -u $SERVICE_NAME -f --lines=20
}

show_recent_logs() {
    echo "=== Recent Sleep Monitor Service Logs ==="
    sudo journalctl -u $SERVICE_NAME --no-pager -n 50
}

case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_status
        ;;
    enable)
        enable_service
        ;;
    disable)
        disable_service
        ;;
    logs)
        show_logs
        ;;
    recent)
        show_recent_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|enable|disable|logs|recent}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the sleep monitor service"
        echo "  stop     - Stop the sleep monitor service"
        echo "  restart  - Restart the sleep monitor service"
        echo "  status   - Show service status"
        echo "  enable   - Enable service to start on boot"
        echo "  disable  - Disable service from starting on boot"
        echo "  logs     - Show real-time service logs"
        echo "  recent   - Show recent service logs (non-interactive)"
        exit 1
        ;;
esac

exit 0
