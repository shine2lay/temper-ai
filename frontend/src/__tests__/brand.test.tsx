/**
 * The Temper mark where the app shows its name (logo handoff, design-lab
 * results/temper-logo/UI-HANDOFF.md).
 *
 * The sidebar used to show a bold "T" letter in the accent colour. It now
 * shows Design's symbol: with the name when the sidebar is open, alone when
 * it is collapsed. Both colourways are in the page and the theme's `dark`
 * class shows one of them, so the tests look at both.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import indexHtml from '../../index.html?raw';
import faviconSvg from '../../public/favicon.svg?raw';
import { AppSidebar } from '@/components/layout/AppSidebar';
import { TokenGate } from '@/components/layout/TokenGate';

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AppSidebar />
    </MemoryRouter>,
  );
}

function colourways(scope: HTMLElement) {
  const symbol = within(scope).getByTestId('temper-symbol');
  const imgs = Array.from(symbol.querySelectorAll('img'));
  return { symbol, imgs, ways: imgs.map((i) => i.dataset.colourway) };
}

describe('sidebar brand', () => {
  beforeEach(() => localStorage.clear());

  it('shows the symbol and the name, and no "T" letter, when open', () => {
    renderSidebar();
    const brand = screen.getByTestId('sidebar-brand');

    const { imgs, ways } = colourways(brand);
    expect(ways).toEqual(['ink', 'reverse']);
    for (const img of imgs) {
      expect(img.getAttribute('src')).toMatch(/temper-symbol(-reverse)?\.svg|^data:image\/svg/);
      // The name is written next to it, so the image itself is not announced.
      expect(img).toHaveAttribute('alt', '');
      expect(Number(img.getAttribute('width'))).toBeGreaterThanOrEqual(24);
    }
    expect(brand).toHaveTextContent(/^Temper AI$/);
    expect(within(brand).queryByText('T', { exact: true })).toBeNull();
  });

  it('shows the symbol alone, named for screen readers, when collapsed', () => {
    localStorage.setItem('temper-sidebar-collapsed', 'true');
    renderSidebar();
    const brand = screen.getByTestId('sidebar-brand');

    const { imgs } = colourways(brand);
    expect(imgs).toHaveLength(2);
    for (const img of imgs) expect(img).toHaveAttribute('alt', 'Temper AI');
    expect(brand.textContent).toBe('');
    expect(within(brand).queryByText('T', { exact: true })).toBeNull();
  });

  it('keeps the symbol through collapsing and opening again', () => {
    renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(screen.getByTestId('sidebar-brand')).not.toHaveTextContent('Temper AI');
    expect(within(screen.getByTestId('sidebar-brand')).getByTestId('temper-symbol')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    expect(screen.getByTestId('sidebar-brand')).toHaveTextContent('Temper AI');
  });

  it('marks the current page without relying on colour alone', () => {
    renderSidebar();
    const current = screen.getByRole('link', { current: 'page' });
    expect(current).toHaveTextContent('Workflows');
    expect(current.className).toMatch(/font-semibold/);
    expect(current.className).toMatch(/border-temper-accent/);
  });
});

describe('sign-in screen brand', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ auth_required: true }), { status: 200 })),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it('shows the Temper AI lockup above the token form', async () => {
    render(
      <TokenGate>
        <p>app</p>
      </TokenGate>,
    );
    const lockup = await screen.findByRole('img', { name: 'Temper AI' });
    expect(lockup).toHaveAttribute('data-testid', 'temper-lockup');
    const light = lockup.querySelector('img');
    expect(light?.getAttribute('src')).toMatch(/temper-ai-lockup\.svg/);
    expect(Number(light?.getAttribute('width'))).toBeGreaterThanOrEqual(160);
    await waitFor(() => expect(screen.getByLabelText('API token')).toBeInTheDocument());
  });
});

describe('browser tab', () => {
  it('links the SVG favicon, a 32 px PNG and the apple-touch icon', () => {
    const doc = new DOMParser().parseFromString(indexHtml, 'text/html');
    const icons = Array.from(doc.querySelectorAll('link[rel="icon"]'));
    const svg = icons.find((l) => l.getAttribute('type') === 'image/svg+xml');
    const png = icons.find((l) => l.getAttribute('type') === 'image/png');
    expect(svg?.getAttribute('href')).toBe('/favicon.svg');
    expect(png?.getAttribute('href')).toBe('/favicon-32.png');
    expect(png?.getAttribute('sizes')).toBe('32x32');
    const touch = doc.querySelector('link[rel="apple-touch-icon"]');
    expect(touch?.getAttribute('href')).toBe('/apple-touch-icon.png');
    expect(touch?.getAttribute('sizes')).toBe('180x180');
  });

  it('keeps the name "Temper AI" in the title', () => {
    const doc = new DOMParser().parseFromString(indexHtml, 'text/html');
    expect(doc.title).toMatch(/^Temper AI\b/);
  });

  it('uses the symbol\'s own colours in the favicon', () => {
    // Green top, ink body, and the reverse (paper) body on dark browser chrome.
    expect(faviconSvg).toContain('#2E7D4F');
    expect(faviconSvg).toContain('#1A1A17');
    expect(faviconSvg).toContain('#F7F5EF');
    expect(faviconSvg).toContain('viewBox="0 0 128 128"');
  });
});
