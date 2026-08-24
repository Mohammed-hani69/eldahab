document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts
    document.querySelectorAll('.alert').forEach(function(el) {
        setTimeout(function() {
            el.style.opacity = '0';
            el.style.transform = 'translateY(-10px)';
            setTimeout(function() { el.remove(); }, 300);
        }, 4000);
    });
});

function confirmDelete(msg) {
    return confirm(msg || 'هل انت متاكد من الحذف؟');
}

function formatNumber(num) {
    return num.toLocaleString('ar-EG');
}
