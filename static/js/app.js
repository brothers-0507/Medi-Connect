// MediConnect - Centralized Pharmacy & Medi-Tracker App JavaScript

// Theme Toggle & Synchronization Helper
function updateThemeIcon() {
    const icon = document.getElementById('theme-icon');
    if (!icon) return;
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    if (currentTheme === 'dark') {
        icon.className = 'ph-bold ph-sun';
        if (icon.parentElement) icon.parentElement.setAttribute('title', 'Switch to Light Mode');
    } else {
        icon.className = 'ph-bold ph-moon';
        if (icon.parentElement) icon.parentElement.setAttribute('title', 'Switch to Dark Mode');
    }
}

function toggleClinicalTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('mediconnect_theme', newTheme);
    updateThemeIcon();
    if (typeof updateThemeButtons === 'function') {
        updateThemeButtons();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateThemeIcon();
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
