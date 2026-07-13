// MediConnect - Centralized Pharmacy & Medi-Tracker App JavaScript
document.addEventListener('DOMContentLoaded', () => {
    console.log('MediConnect Application Initialized.');
    
    // Auto fadeout flash alerts after 6 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            setTimeout(() => {
                alert.remove();
            }, 600);
        }, 6000);
    });
});
