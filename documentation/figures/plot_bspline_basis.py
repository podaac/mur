#!/usr/bin/env python3
"""
Visualize cubic B-spline basis functions used in MRVA.

B-splines are mathematical basis functions with key properties:
1. Local support: Each basis function is non-zero only over 4 grid cells
2. Smoothness: Cubic B-splines have continuous 2nd derivatives
3. Partition of unity: All basis functions sum to 1 at any point
4. Non-negativity: Always >= 0

The SST field is represented as: SST(x,y) = Σ c_ij * B_i(x) * B_j(y)
where c_ij are the coefficients we solve for.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import BSpline

def cubic_bspline_basis(t):
    """
    Evaluate the cubic B-spline basis function centered at t=0.

    This is the "cardinal" cubic B-spline, non-zero on [-2, 2].

    The piecewise formula:
        B(t) = (2-|t|)³/6                      for 1 <= |t| < 2
        B(t) = (4 - 6t² + 3|t|³)/6             for 0 <= |t| < 1
    """
    t = np.atleast_1d(t).astype(float)
    result = np.zeros_like(t)

    abs_t = np.abs(t)

    # Region |t| < 1
    mask1 = abs_t < 1
    result[mask1] = (4 - 6*abs_t[mask1]**2 + 3*abs_t[mask1]**3) / 6

    # Region 1 <= |t| < 2
    mask2 = (abs_t >= 1) & (abs_t < 2)
    result[mask2] = (2 - abs_t[mask2])**3 / 6

    return result


def plot_single_bspline():
    """Plot a single cubic B-spline basis function."""
    fig, ax = plt.subplots(figsize=(10, 4))

    t = np.linspace(-3, 3, 500)
    B = cubic_bspline_basis(t)

    ax.plot(t, B, 'b-', linewidth=2, label='Cubic B-spline B(t)')
    ax.axhline(y=0, color='k', linewidth=0.5)
    ax.axvline(x=0, color='k', linewidth=0.5)

    # Mark the knot points
    for knot in [-2, -1, 0, 1, 2]:
        ax.axvline(x=knot, color='gray', linestyle='--', linewidth=0.5, alpha=0.7)
        ax.plot(knot, cubic_bspline_basis(knot), 'ro', markersize=6)

    ax.set_xlabel('t (distance from center, in coefficient grid spacings)', fontsize=12)
    ax.set_ylabel('B(t)', fontsize=12)
    ax.set_title('Single Cubic B-spline Basis Function\n(non-zero only within 2 grid spacings of center)', fontsize=14)
    ax.set_xlim(-3, 3)
    ax.set_ylim(-0.05, 0.75)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    # Annotate key properties
    ax.annotate('Local support:\nonly 4 cells wide', xy=(1.5, 0.15), fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    ax.annotate(f'Peak value: {cubic_bspline_basis(0)[0]:.3f}', xy=(0, 0.67),
                xytext=(0.5, 0.6), fontsize=10,
                arrowprops=dict(arrowstyle='->', color='gray'))

    plt.tight_layout()
    return fig


def plot_bspline_family():
    """Plot multiple translated B-splines showing how they tile the domain."""
    fig, ax = plt.subplots(figsize=(12, 5.5))

    t = np.linspace(-1, 8, 1000)
    colors = plt.cm.tab10(np.linspace(0, 1, 8))

    # Plot B-splines centered at different coefficient grid points
    total = np.zeros_like(t)
    for i, center in enumerate(range(-1, 7)):
        B = cubic_bspline_basis(t - center)
        ax.plot(t, B, color=colors[i], linewidth=1.5, label=f'B centered at coeff grid {center}')
        total += B

    # Plot the sum (should be 1 everywhere in the interior)
    ax.plot(t, total, 'k--', linewidth=2, label='Sum of all B-splines = 1')

    # Show an observation between grid points
    obs_pos = 3.7
    ax.axvline(x=obs_pos, color='red', linestyle='-', linewidth=2, alpha=0.7, label=f'Observation at x={obs_pos}')

    # Mark the 4 basis values at the observation location
    for center in [2, 3, 4, 5]:
        bval = cubic_bspline_basis(obs_pos - center)[0]
        if bval > 0.001:
            ax.plot(obs_pos, bval, 'ro', markersize=8, zorder=10)
            ax.annotate(f'B({obs_pos - center:.1f})={bval:.3f}',
                       xy=(obs_pos, bval), xytext=(obs_pos + 0.3, bval + 0.03),
                       fontsize=9, color='red',
                       arrowprops=dict(arrowstyle='->', color='red', lw=0.8))

    ax.axhline(y=1, color='gray', linestyle=':', linewidth=1)
    ax.axhline(y=0, color='k', linewidth=0.5)

    ax.set_xlabel('Coefficient grid position (B-spline centers at integer positions)', fontsize=12)
    ax.set_ylabel('B(t)', fontsize=12)
    ax.set_title('Family of Cubic B-splines: Partition of Unity\n'
                 'Any vertical line intersects at most 4 non-zero B-splines, and their values sum to 1',
                 fontsize=13)
    ax.set_xlim(-1, 8)
    ax.set_ylim(-0.05, 1.15)
    ax.legend(loc='upper right', fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    return fig


def plot_2d_bspline():
    """Plot a 2D tensor-product B-spline basis function."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    # Create 2D grid
    x = np.linspace(-3, 3, 200)
    y = np.linspace(-3, 3, 200)
    X, Y = np.meshgrid(x, y)

    # 2D B-spline is tensor product: B(x,y) = B(x) * B(y)
    Bx = cubic_bspline_basis(X)
    By = cubic_bspline_basis(Y)
    B2D = Bx * By

    # Plot 1D slices
    ax = axes[0]
    ax.plot(x, cubic_bspline_basis(x), 'b-', linewidth=2)
    ax.set_title('1D B-spline B(x)', fontsize=12)
    ax.set_xlabel('x')
    ax.set_ylabel('B(x)')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-3, 3)

    # Plot 2D contour
    ax = axes[1]
    contour = ax.contourf(X, Y, B2D, levels=20, cmap='Blues')
    ax.contour(X, Y, B2D, levels=10, colors='navy', linewidths=0.5, alpha=0.5)
    ax.set_title('2D B-spline B(x)·B(y)\n(Tensor product)', fontsize=12)
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_aspect('equal')
    plt.colorbar(contour, ax=ax, label='B(x,y)')

    # Plot 3D surface
    ax = axes[2]
    ax.remove()
    ax = fig.add_subplot(1, 3, 3, projection='3d')

    # Subsample for 3D plot
    stride = 5
    ax.plot_surface(X[::stride, ::stride], Y[::stride, ::stride],
                    B2D[::stride, ::stride], cmap='Blues',
                    edgecolor='navy', linewidth=0.2, alpha=0.8)
    ax.set_title('3D view of 2D B-spline', fontsize=12)
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_zlabel('B(x,y)')

    plt.tight_layout()
    return fig


def plot_field_reconstruction():
    """
    Show how a field is reconstructed from B-spline coefficients.

    This demonstrates: SST(x) = Σ c_i * B_i(x)
    """
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # Define some example coefficients (simulating a temperature pattern)
    np.random.seed(42)
    n_coeffs = 10
    # Make coefficients look like a temperature gradient with some variation
    coefficients = 15 + 5 * np.sin(np.linspace(0, 2*np.pi, n_coeffs)) + np.random.randn(n_coeffs) * 0.5

    x = np.linspace(0, n_coeffs-1, 500)

    # Plot 1: Individual weighted basis functions
    ax = axes[0, 0]
    colors = plt.cm.coolwarm(np.linspace(0, 1, n_coeffs))
    for i in range(n_coeffs):
        B_weighted = coefficients[i] * cubic_bspline_basis(x - i)
        ax.plot(x, B_weighted, color=colors[i], linewidth=1, alpha=0.7,
                label=f'c_{i}·B_{i}' if i < 5 else None)
    ax.set_title('Individual weighted basis functions: c_i · B_i(x)', fontsize=12)
    ax.set_xlabel('x (coefficient grid position)')
    ax.set_ylabel('Contribution to field')
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)

    # Plot 2: Cumulative sum showing reconstruction
    ax = axes[0, 1]
    cumulative = np.zeros_like(x)
    for i in range(n_coeffs):
        B_weighted = coefficients[i] * cubic_bspline_basis(x - i)
        cumulative += B_weighted
        if i in [0, 2, 4, 6, 9]:
            ax.plot(x, cumulative, linewidth=1.5, alpha=0.7, label=f'Sum up to B_{i}')
    ax.set_title('Progressive reconstruction: Σ c_i · B_i(x)', fontsize=12)
    ax.set_xlabel('x (coefficient grid position)')
    ax.set_ylabel('Reconstructed field')
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)

    # Plot 3: Final reconstructed field vs coefficients
    ax = axes[1, 0]
    final_field = np.zeros_like(x)
    for i in range(n_coeffs):
        final_field += coefficients[i] * cubic_bspline_basis(x - i)

    ax.plot(x, final_field, 'b-', linewidth=2, label='Reconstructed field')
    ax.scatter(range(n_coeffs), coefficients, c='red', s=50, zorder=5,
               label='Coefficient values c_i')
    ax.set_title('Final result: SST(x) = Σ c_i · B_i(x)', fontsize=12)
    ax.set_xlabel('x (coefficient grid position)')
    ax.set_ylabel('Temperature (°C)')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    # Plot 4: Explanation text
    ax = axes[1, 1]
    ax.axis('off')
    explanation = """
    How B-splines represent the SST field:

    1. The domain is covered by a grid of coefficients c_ij

    2. Each coefficient has an associated B-spline basis
       function B_i(x)·B_j(y) centered at that grid point

    3. The B-splines have LOCAL SUPPORT (only 4 cells wide)
       → Changing one coefficient only affects nearby region
       → Sparse matrices, efficient computation

    4. The field at any point is the weighted sum:
       SST(x,y) = Σ_ij c_ij · B_i(x) · B_j(y)

    5. B-splines are SMOOTH (C² continuous)
       → No artificial discontinuities in the SST field

    6. The coefficients c_ij are what MRVA solves for
       by fitting to observations while enforcing smoothness

    Key insight: B-splines are purely mathematical—
    they know nothing about temperature. They just provide
    a smooth, local, efficient way to represent ANY field.
    """
    ax.text(0.05, 0.95, explanation, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    plt.tight_layout()
    return fig


def plot_multiscale_bsplines():
    """
    Show how B-spline grids relate at different scales (the multi-resolution aspect).
    """
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    scales = [
        (4, 'L=4: Coarse scale (~312 km)', 'blue'),
        (8, 'L=5: Medium scale (~156 km)', 'green'),
        (16, 'L=6: Fine scale (~78 km)', 'red'),
    ]

    x = np.linspace(0, 16, 1000)

    for ax, (n_basis, title, color) in zip(axes, scales):
        spacing = 16 / n_basis

        # Plot each basis function
        for i in range(n_basis + 3):  # Extra for boundary
            center = i * spacing - spacing
            B = cubic_bspline_basis((x - center) / spacing) / spacing * 4  # Normalize height for visibility
            ax.fill_between(x, B, alpha=0.3, color=color)
            ax.plot(x, B, color=color, linewidth=0.5)

        ax.set_title(title, fontsize=12)
        ax.set_ylabel('B(x)')
        ax.set_ylim(0, 1.5)
        ax.grid(True, alpha=0.3)

        # Mark grid points
        grid_points = np.arange(0, 17, spacing)
        ax.scatter(grid_points[grid_points <= 16], np.zeros(len(grid_points[grid_points <= 16])),
                   color=color, s=30, zorder=5)

    axes[-1].set_xlabel('Domain position (arbitrary units)')

    fig.suptitle('Multi-scale B-spline Grids\n(Grid doubles at each scale → 2× more basis functions)',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    return fig


if __name__ == '__main__':
    import os

    # Create output directory if needed
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("Generating B-spline visualization figures...")

    # Generate all figures
    fig1 = plot_single_bspline()
    fig1.savefig(os.path.join(script_dir, 'bspline_single.png'), dpi=150, bbox_inches='tight')
    print("  Saved: bspline_single.png")

    fig2 = plot_bspline_family()
    fig2.savefig(os.path.join(script_dir, 'bspline_family.png'), dpi=150, bbox_inches='tight')
    print("  Saved: bspline_family.png")

    fig3 = plot_2d_bspline()
    fig3.savefig(os.path.join(script_dir, 'bspline_2d.png'), dpi=150, bbox_inches='tight')
    print("  Saved: bspline_2d.png")

    fig4 = plot_field_reconstruction()
    fig4.savefig(os.path.join(script_dir, 'bspline_reconstruction.png'), dpi=150, bbox_inches='tight')
    print("  Saved: bspline_reconstruction.png")

    fig5 = plot_multiscale_bsplines()
    fig5.savefig(os.path.join(script_dir, 'bspline_multiscale.png'), dpi=150, bbox_inches='tight')
    print("  Saved: bspline_multiscale.png")

    print("\nDone! Run with 'plt.show()' to display interactively.")
    plt.show()
