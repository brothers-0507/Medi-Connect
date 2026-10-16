// MediConnect - Centralized Pharmacy & Medi-Tracker App JavaScript

// Theme Toggle & Synchronization Helper
function updateThemeIcon() {
    const icon = document.getElementById('theme-icon');
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const isDark = currentTheme === 'dark';

    if (icon) {
        icon.className = isDark ? 'ph-bold ph-sun' : 'ph-bold ph-moon';
        if (icon.parentElement) {
            icon.parentElement.setAttribute('title', isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode');
        }
    }

    // Sync mobile drawer theme icons & text
    document.querySelectorAll('.theme-toggle-icon-mobile').forEach(el => {
        el.className = isDark ? 'ph-bold ph-sun theme-toggle-icon-mobile' : 'ph-bold ph-moon theme-toggle-icon-mobile';
    });
    document.querySelectorAll('.theme-label-mobile').forEach(el => {
        el.textContent = isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    });
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

// Mobile Slide-out Navigation Drawer
function toggleMobileNavDrawer(forceState) {
    const drawer = document.getElementById('mobile-nav-drawer');
    const backdrop = document.getElementById('mobile-nav-backdrop');
    const toggleBtn = document.getElementById('mobile-nav-toggle');
    const icon = document.getElementById('mobile-hamburger-icon');
    
    if (!drawer || !backdrop) return;
    
    const isOpen = typeof forceState === 'boolean' ? forceState : !drawer.classList.contains('open');
    
    if (isOpen) {
        drawer.classList.add('open');
        backdrop.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'true');
        if (icon) icon.className = 'ph-bold ph-x';
        document.body.style.overflow = 'hidden';
    } else {
        drawer.classList.remove('open');
        backdrop.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
        if (icon) icon.className = 'ph-bold ph-list';
        document.body.style.overflow = '';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateThemeIcon();
    console.log('MediConnect Application Initialized.');

    // Close mobile drawer on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            toggleMobileNavDrawer(false);
        }
    });

    // Close drawer when clicking outside
    window.addEventListener('resize', () => {
        if (window.innerWidth >= 768) {
            toggleMobileNavDrawer(false);
        }
    });
    
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
