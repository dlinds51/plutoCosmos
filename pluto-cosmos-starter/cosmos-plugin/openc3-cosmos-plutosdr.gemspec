Gem::Specification.new do |spec|
  spec.name          = 'openc3-cosmos-plutosdr'
  spec.version       = '0.3.0'
  spec.authors       = ['Pluto COSMOS Starter']
  spec.summary       = 'ADALM-PLUTO spectrum and ADS-B target for OpenC3 COSMOS'
  spec.description   = 'PlutoSDR spectrum waterfall and ADS-B readsb aircraft telemetry in native COSMOS screens'
  spec.files         = Dir.glob('plugin.txt') + Dir.glob('targets/**/*').select { |f| File.file?(f) }
  spec.require_paths = ['lib']
end
