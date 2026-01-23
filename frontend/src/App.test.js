import { render, screen } from '@testing-library/react';
import App from './App';

test('renders CyberRisk application', () => {
  render(<App />);
  // Use getAllByText since there may be multiple elements containing "CyberRisk"
  const appElements = screen.getAllByText(/CyberRisk/i);
  expect(appElements.length).toBeGreaterThan(0);
});
